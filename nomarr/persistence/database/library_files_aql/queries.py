"""Query operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesQueriesMixin:
    """Query operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def get_file_by_id(self, file_id: str) -> dict[str, Any] | None:
        """Get library file by _id.

        Args:
            file_id: Document _id (e.g., "library_files/12345")

        Returns:
            File dict or None if not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            RETURN DOCUMENT(@file_id)
            """,
                bind_vars={"file_id": file_id},
            ),
        )
        result: dict[str, Any] = next(cursor, {})
        return result or None

    def get_files_by_ids_with_tags(self, file_ids: list[str]) -> list[dict[str, Any]]:
        """Get files by IDs with their associated tags.

        Used for batch lookup of files (e.g., for browse UI).
        Preserves order of input IDs where possible.

        Args:
            file_ids: List of document _ids to fetch

        Returns:
            List of file dicts with 'tags' array containing tag details

        """
        if not file_ids:
            return []

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file_id IN @file_ids
                LET file = DOCUMENT(file_id)
                FILTER file != null
                LET tags = (
                    FOR edge IN song_has_tags
                        FILTER edge._from == file._id
                        LET tag = DOCUMENT(edge._to)
                        FILTER tag != null
                        RETURN {
                            key: tag.rel,
                            value: tag.value,
                            type: IS_NUMBER(tag.value) ? "float" : "string",
                            is_nomarr: STARTS_WITH(tag.rel, "nom:")
                        }
                )
                LET lib_id = FIRST(
                    FOR lib IN INBOUND file._id library_contains_file
                        LIMIT 1
                        RETURN lib._id
                )
                RETURN MERGE(file, { tags: tags, library_id: lib_id })
            """,
                bind_vars=cast("dict[str, Any]", {"file_ids": file_ids}),
            ),
        )
        return list(cursor)

    def get_library_file(self, path: str, library_id: str | None = None) -> dict[str, Any] | None:
        """Get library file by path.

        Searches by normalized_path first (canonical identity), then falls back
        to absolute path for compatibility with existing documents.

        When library_id is provided, uses edge traversal via library_contains_file
        rather than filtering on a library_id field.

        Args:
            path: File path (absolute or relative to library root)
            library_id: Optional library _id to restrict search (uses edge traversal)

        Returns:
            File dict or None if not found

        """
        bind_vars: dict[str, Any] = {"path": path}

        if library_id is not None:
            # Use edge traversal to find files owned by this library
            query = """
                FOR file IN OUTBOUND @library_id library_contains_file
                    FILTER file.normalized_path == @path OR file.path == @path
                    SORT file._key
                    LIMIT 1
                    RETURN file
            """
            bind_vars["library_id"] = library_id
        else:
            # No library filter — scan all files
            query = """
                FOR file IN library_files
                    FILTER file.normalized_path == @path OR file.path == @path
                    SORT file._key
                    LIMIT 1
                    RETURN file
            """

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=bind_vars))
        result = list(cursor)
        return result[0] if result else None

    def get_files_by_paths_bulk(self, paths: list[str]) -> dict[str, dict[str, Any]]:
        """Get multiple library file records by path in one AQL query.

        Matches on ``normalized_path`` or ``path`` (abs path fallback).
        Returns the first match per input path.

        Args:
            paths: List of file paths (absolute or relative to library root)

        Returns:
            Dict mapping input path -> file document.
            Paths with no match are absent from the result.

        """
        if not paths:
            return {}

        query = """
            FOR file IN library_files
                FILTER file.normalized_path IN @paths OR file.path IN @paths
                RETURN file
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"paths": paths})),
        )
        # Build lookup: map both normalized_path and path -> doc, prefer normalized_path
        path_set = set(paths)
        result: dict[str, dict[str, Any]] = {}
        for doc in cursor:
            norm = doc.get("normalized_path")
            abs_path = doc.get("path")
            # Map whichever input path key we used
            if norm and norm in path_set and norm not in result:
                result[norm] = doc
            if abs_path and abs_path in path_set and abs_path not in result:
                result[abs_path] = doc
        return result

    def detect_nd_path_prefix(self, nd_path: str) -> str | None:
        """Detect the Navidrome path prefix by matching an absolute ND path against
        normalized_path suffixes stored in library_files.

        For example, if ``nd_path`` is ``/music/Artist/Album/track.flac`` and a
        library file has ``normalized_path = "Artist/Album/track.flac"``, this
        returns ``"/music/"`` (the prefix to strip).

        Returns:
            Detected prefix string (may be empty ``""`` if paths already match),
            or ``None`` if no library file matches the given path as a suffix.
        """
        query = """
        FOR f IN library_files
            FILTER LENGTH(f.normalized_path) > 0
                AND ENDS_WITH(@nd_path, f.normalized_path)
            LIMIT 1
            RETURN SUBSTRING(@nd_path, 0, LENGTH(@nd_path) - LENGTH(f.normalized_path))
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"nd_path": nd_path})),
        )
        result: list[str] = list(cursor)
        cursor.close(ignore_missing=True)
        return result[0] if result else None

    def get_file_modified_times(self) -> dict[str, int]:
        """Get all file paths and their modified times.

        Returns:
            Dict mapping file path to modified_time (milliseconds)

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN { path: file.path, modified_time: file.modified_time }
            """,
            ),
        )
        return {item["path"]: item["modified_time"] for item in cursor}

    def list_library_files(
        self,
        limit: int = 100,
        offset: int = 0,
        artist: str | None = None,
        album: str | None = None,
        library_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List library files with optional filtering.

        Args:
            limit: Maximum number of files to return
            offset: Number of files to skip
            artist: Filter by artist name
            album: Filter by album name
            library_id: Filter by library ID (uses edge traversal)

        Returns:
            Tuple of (files list, total count)

        """
        # Build filter conditions (excluding library_id which uses edge traversal)
        filters = []
        if artist:
            filters.append("file.artist == @artist")
        if album:
            filters.append("file.album == @album")
        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        # Build bind_vars for filter conditions
        bind_vars: dict[str, Any] = {}
        if artist:
            bind_vars["artist"] = artist
        if album:
            bind_vars["album"] = album

        if library_id is not None:
            # Use edge traversal for library filtering
            bind_vars["library_id"] = library_id

            # Get total count via edge traversal
            count_query = f"""
                FOR file IN OUTBOUND @library_id library_contains_file
                    {filter_clause}
                    COLLECT WITH COUNT INTO total
                    RETURN total
            """
            count_cursor = cast("Cursor", self.db.aql.execute(count_query, bind_vars=bind_vars))
            total = next(count_cursor, 0)

            # Get paginated results via edge traversal
            paginated_bind_vars = {**bind_vars, "limit": limit, "offset": offset}
            query = f"""
                FOR file IN OUTBOUND @library_id library_contains_file
                    {filter_clause}
                    SORT file.artist, file.album, file.title
                    LIMIT @offset, @limit
                    RETURN file
            """
            cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=paginated_bind_vars))
            files = list(cursor)
        else:
            # No library filter — scan all files
            count_query = f"""
                FOR file IN library_files
                    {filter_clause}
                    COLLECT WITH COUNT INTO total
                    RETURN total
            """
            count_cursor = cast("Cursor", self.db.aql.execute(count_query, bind_vars=bind_vars))
            total = next(count_cursor, 0)

            paginated_bind_vars = {**bind_vars, "limit": limit, "offset": offset}
            query = f"""
                FOR file IN library_files
                    {filter_clause}
                    SORT file.artist, file.album, file.title
                    LIMIT @offset, @limit
                    RETURN file
            """
            cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=paginated_bind_vars))
            files = list(cursor)

        return files, total

    def get_all_library_paths(self) -> list[str]:
        """Get all library file paths.

        Returns:
            List of file paths

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN file.path
            """,
            ),
        )
        return list(cursor)

    def get_tagged_file_paths(self) -> list[str]:
        """Get all file paths that have been tagged.

        Uses INBOUND traversal on ``file_states/tagged`` to identify tagged files.

        Returns:
            List of file paths that have been tagged

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER LENGTH(
                    FOR v IN 1..1 INBOUND "file_states/tagged" file_has_state
                        FILTER v._id == file._id
                        RETURN 1
                ) > 0
                RETURN file.path
            """,
            ),
        )
        return list(cursor)

    def search_library_files_with_tags(
        self,
        query_text: str = "",
        artist: str | None = None,
        album: str | None = None,
        tag_key: str | None = None,
        tag_value: str | None = None,
        tagged_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search library files with optional filtering.

        Returns files WITH their tags in a single result.

        Args:
            query_text: Text search query for artist/album/title
            artist: Filter by artist name
            album: Filter by album name
            tag_key: Filter by files that have this tag key (rel)
            tag_value: Filter by specific tag key=value (requires tag_key)
            tagged_only: Only return tagged files
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            Tuple of (files_list, total_count). Each dict in files_list
            contains all file fields merged with ``tags`` (list of tag dicts)
            and ``library_id`` (derived via INBOUND edge traversal on
            ``library_contains_file``).

        """
        # Build filter conditions
        filters = []

        if tag_key and tag_value:
            filters.append(
                """
            LENGTH(
                FOR edge IN song_has_tags
                    FILTER edge._from == file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == @tag_key AND tag.value == @tag_value
                    LIMIT 1
                    RETURN 1
            ) > 0
            """,
            )
        elif tag_key:
            filters.append(
                """
            LENGTH(
                FOR edge IN song_has_tags
                    FILTER edge._from == file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == @tag_key
                    LIMIT 1
                    RETURN 1
            ) > 0
            """,
            )

        if query_text:
            filters.append(
                "(LIKE(file.artist, @q_pattern, true) OR "
                "LIKE(file.album, @q_pattern, true) OR "
                "LIKE(file.title, @q_pattern, true))",
            )

        if artist:
            filters.append("file.artist == @artist")

        if album:
            filters.append("file.album == @album")

        if tagged_only:
            filters.append(
                """LENGTH(
                FOR v IN 1..1 INBOUND "file_states/tagged" file_has_state
                    FILTER v._id == file._id
                    RETURN 1
            ) > 0"""
            )

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        # Build filter-only bind vars (for count query)
        filter_bind_vars: dict[str, Any] = {}
        if tag_key:
            filter_bind_vars["tag_key"] = tag_key
        if tag_value:
            filter_bind_vars["tag_value"] = tag_value
        if query_text:
            filter_bind_vars["q_pattern"] = f"%{query_text}%"
        if artist:
            filter_bind_vars["artist"] = artist
        if album:
            filter_bind_vars["album"] = album

        # Get total count (without limit/offset)
        count_cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast("dict[str, Any]", filter_bind_vars),
            ),
        )
        total = next(count_cursor, 0)

        # Build full bind vars (with pagination) for data query
        bind_vars = {**filter_bind_vars, "limit": limit, "offset": offset}

        # Get files with tags (using unified schema)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                SORT file.artist, file.album, file.title
                LIMIT @offset, @limit
                LET tags = (
                    FOR edge IN song_has_tags
                        FILTER edge._from == file._id
                        LET tag = DOCUMENT(edge._to)
                        FILTER tag != null
                        SORT tag.rel
                        RETURN {{
                            key: tag.rel,
                            value: tag.value,
                            type: IS_NUMBER(tag.value) ? "float" : "string",
                            is_nomarr: STARTS_WITH(tag.rel, "nom:")
                        }}
                )
                LET lib_id = FIRST(FOR lib IN INBOUND file._id library_contains_file LIMIT 1 RETURN lib._id)
                RETURN MERGE(file, {{ tags: tags, library_id: lib_id }})
            """,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )

        return list(cursor), total

    def get_recently_processed(
        self,
        limit: int = 20,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recently processed (tagged) files ordered by scanned_at descending.

        Filters to tagged files via INBOUND traversal on ``file_states/tagged``
        and sorts by ``file.scanned_at DESC``.

        When library_id is provided, filters files using edge traversal via
        ``library_contains_file``.

        Args:
            limit: Maximum number of files to return.
            library_id: Optional library _id to filter by (uses edge traversal).

        Returns:
            List of {file_id, path, title, artist, album, scanned_at}
            sorted by scanned_at DESC.
        """
        bind_vars: dict[str, Any] = {"limit": limit}

        if library_id:
            bind_vars["library_id"] = library_id
            query = """
            FOR file IN 1..1 INBOUND "file_states/tagged" file_has_state
                FILTER LENGTH(
                    FOR e IN library_contains_file
                        FILTER e._from == @library_id AND e._to == file._id
                        LIMIT 1
                        RETURN 1
                ) > 0
                SORT file.scanned_at DESC
                LIMIT @limit
                RETURN {
                    file_id: file._id,
                    path: file.normalized_path,
                    title: file.title,
                    artist: file.artist,
                    album: file.album,
                    scanned_at: file.scanned_at
                }
            """
        else:
            query = """
            FOR file IN 1..1 INBOUND "file_states/tagged" file_has_state
                SORT file.scanned_at DESC
                LIMIT @limit
                RETURN {
                    file_id: file._id,
                    path: file.normalized_path,
                    title: file.title,
                    artist: file.artist,
                    album: file.album,
                    scanned_at: file.scanned_at
                }
            """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=bind_vars))
        return list(cursor)

    def get_folder_rel_paths(self, library_id: str) -> set[str]:
        """Get all known folder rel_paths for a library.

        Queries the ``library_folders`` cache collection via edge traversal,
        since folder ownership is tracked via ``library_contains_folder`` edges.

        Args:
            library_id: Library document ``_id``

        Returns:
            Set of POSIX folder rel_paths (e.g., ``{"Rock/Beatles", ""}``).  Empty string
            represents the library root folder.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR folder IN OUTBOUND @library_id library_contains_folder
                RETURN folder.path
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        return set(cursor)

    def get_files_for_folder(
        self,
        library_id: str,
        folder_rel_path: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all file documents for a single folder.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Args:
            library_id: Library document ``_id``
            folder_rel_path: POSIX relative folder path (``""`` for library root)

        Returns:
            Dict mapping absolute file path → file document.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN OUTBOUND @library_id library_contains_file
                FILTER (
                    (@folder_rel_path == "" AND NOT CONTAINS(file.normalized_path, "/"))
                    OR
                    (@folder_rel_path != "" AND STARTS_WITH(file.normalized_path, CONCAT(@folder_rel_path, "/")))
                )
                RETURN file
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"library_id": library_id, "folder_rel_path": folder_rel_path},
                ),
            ),
        )
        return {f["path"]: f for f in cursor}

    def get_files_for_folders(
        self,
        library_id: str,
        folder_rel_paths: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch-fetch file documents for multiple folders.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Intended for loading file docs for vanished folders before the
        scan loop starts so they can seed the ``missing_docs`` list.

        Args:
            library_id: Library document ``_id``
            folder_rel_paths: POSIX relative paths of the folders.

        Returns:
            Dict mapping absolute file path → file document.

        """
        if not folder_rel_paths:
            return {}
        has_root = "" in folder_rel_paths
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            LET has_root = @has_root
            FOR file IN OUTBOUND @library_id library_contains_file
                FILTER (
                    (has_root AND NOT CONTAINS(file.normalized_path, "/"))
                    OR
                    LENGTH(
                        FOR fp IN @folder_rel_paths
                            FILTER fp != "" AND STARTS_WITH(file.normalized_path, CONCAT(fp, "/"))
                            LIMIT 1
                            RETURN 1
                    ) > 0
                )
                RETURN file
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "folder_rel_paths": folder_rel_paths,
                        "has_root": has_root,
                    },
                ),
            ),
        )
        return {f["path"]: f for f in cursor}

    def count_library_files(self, library_id: str) -> int:
        """Count total files for a library.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Used to set accurate progress totals at scan start without
        loading all file documents.

        Args:
            library_id: Library document ``_id``

        Returns:
            Total number of file documents for the library.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN OUTBOUND @library_id library_contains_file
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        return next(iter(cursor), 0)
