"""Library files operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

from typing import Any, Literal, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class LibraryFilesOperations:
    """Operations for the library_files collection."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("library_files")

    def upsert_library_file(
        self,
        path: LibraryPath,
        library_id: str,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        calibration: dict[str, Any] | None = None,
        last_tagged_at: int | None = None,
    ) -> str:
        """Insert or update a library file entry.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            library_id: ID of owning library
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            calibration: Calibration metadata as dict
            last_tagged_at: Last tagging timestamp

        Returns:
            Document _id (e.g., "library_files/12345")

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot upsert invalid path ({path.status}): {path.reason}")

        scanned_at = now_ms()
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            UPSERT { library_id: @library_id, path: @path }
            INSERT {
                library_id: @library_id,
                path: @path,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                calibration: @calibration,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at,
                tagged: 0,
                tagged_version: null,
                chromaprint: null,
                needs_tagging: 1,
                is_valid: 1
            }
            UPDATE {
                library_id: @library_id,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                calibration: @calibration,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at != null ? @last_tagged_at : OLD.last_tagged_at
            }
            IN library_files
            RETURN NEW._id
            """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "library_id": library_id,
                        "path": str(path.relative),  # Store relative path
                        "file_size": file_size,
                        "modified_time": modified_time,
                        "duration_seconds": duration_seconds,
                        "artist": artist,
                        "album": album,
                        "title": title,
                        "calibration": calibration or {},
                        "scanned_at": scanned_at,
                        "last_tagged_at": last_tagged_at,
                    },
                ),
            ),
        )

        result = next(cursor)
        return str(result)  # Returns _id (e.g., "library_files/12345")

    def mark_file_tagged(self, file_id: str, tagged_version: str) -> None:
        """Mark file as tagged.

        Accepts _id directly (no lookup needed).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            tagged_version: Tagged version string
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                tagged: 1,
                tagged_version: @version,
                last_tagged_at: @timestamp,
                needs_tagging: 0
            } IN library_files
            """,
            bind_vars=cast(dict[str, Any], {"file_id": file_id, "version": tagged_version, "timestamp": now_ms()}),
        )

    def get_file_by_id(self, file_id: str) -> dict[str, Any] | None:
        """Get library file by _id.

        Args:
            file_id: Document _id (e.g., "library_files/12345")

        Returns:
            File dict or None if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            RETURN DOCUMENT(@file_id)
            """,
                bind_vars={"file_id": file_id},
            ),
        )
        result: dict[str, Any] = next(cursor, {})
        return result if result else None

    def get_library_file(self, path: str, library_id: int | None = None) -> dict[str, Any] | None:
        """Get library file by path.

        Args:
            path: File path (relative to library root)
            library_id: Optional library ID to restrict search

        Returns:
            File dict or None if not found
        """
        query = """
            FOR file IN library_files
                FILTER file.path == @path
        """
        bind_vars: dict[str, Any] = {"path": path}

        if library_id is not None:
            query += " AND file.library_id == @library_id"
            bind_vars["library_id"] = library_id

        query += """
                SORT file._key
                LIMIT 1
                RETURN file
        """

        cursor = cast(Cursor, self.db.aql.execute(query, bind_vars=bind_vars))
        result = list(cursor)
        return result[0] if result else None

    def get_file_modified_times(self) -> dict[str, int]:
        """Get all file paths and their modified times.

        Returns:
            Dict mapping file path to modified_time (milliseconds)
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN { path: file.path, modified_time: file.modified_time }
            """
            ),
        )
        return {item["path"]: item["modified_time"] for item in cursor}

    def list_library_files(
        self,
        limit: int = 100,
        offset: int = 0,
        artist: str | None = None,
        album: str | None = None,
        library_id: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List library files with optional filtering.

        Args:
            limit: Maximum number of files to return
            offset: Number of files to skip
            artist: Filter by artist name
            album: Filter by album name
            library_id: Filter by library ID

        Returns:
            Tuple of (files list, total count)
        """
        # Build filter conditions
        filters = []
        bind_vars: dict[str, Any] = {"limit": limit, "offset": offset}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        if artist:
            filters.append("file.artist == @artist")
            bind_vars["artist"] = artist

        if album:
            filters.append("file.album == @album")
            bind_vars["album"] = album

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        # Get total count
        count_query = f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
        """
        count_cursor = cast(Cursor, self.db.aql.execute(count_query, bind_vars=bind_vars))
        total = next(count_cursor, 0)

        # Get paginated results
        query = f"""
            FOR file IN library_files
                {filter_clause}
                SORT file.artist, file.album, file.title
                LIMIT @offset, @limit
                RETURN file
        """
        cursor = cast(Cursor, self.db.aql.execute(query, bind_vars=bind_vars))
        files = list(cursor)

        return files, total

    def get_all_library_paths(self) -> list[str]:
        """Get all library file paths.

        Returns:
            List of file paths
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN file.path
            """
            ),
        )
        return list(cursor)

    def get_tagged_file_paths(self) -> list[str]:
        """Get all file paths that have been tagged.

        Returns:
            List of file paths that have been tagged
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.tagged == 1
                RETURN file.path
            """
            ),
        )
        return list(cursor)

    def delete_library_file(self, file_id: str) -> None:
        """Remove a file from the library.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
        """
        self.db.aql.execute(
            """
            REMOVE PARSE_IDENTIFIER(@file_id).key IN library_files
            """,
            bind_vars={"file_id": file_id},
        )

    def get_library_stats(self, library_id: int | None = None) -> dict[str, Any]:
        """Get library statistics.

        Args:
            library_id: Optional library ID to filter

        Returns:
            Dict with: total_files, total_artists, total_albums, total_duration, total_size
        """
        filter_clause = "FILTER file.library_id == @library_id" if library_id is not None else ""
        bind_vars = {"library_id": library_id} if library_id is not None else {}

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT AGGREGATE
                    total_files = COUNT(1),
                    total_artists = COUNT_DISTINCT(file.artist),
                    total_albums = COUNT_DISTINCT(file.album),
                    total_duration = SUM(file.duration_seconds),
                    total_size = SUM(file.file_size)
                RETURN {{
                    total_files,
                    total_artists,
                    total_albums,
                    total_duration,
                    total_size
                }}
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )
        result: dict[str, Any] = next(cursor, {})
        return result

    def clear_library_data(self) -> None:
        """Clear all library files and file_tags.

        WARNING: This is a cross-collection operation that deletes from:
        - file_tags
        - library_files
        """
        # Delete file_tags first (edge collection)
        self.db.aql.execute("FOR edge IN file_tags REMOVE edge IN file_tags")
        # Delete library_files
        self.db.aql.execute("FOR file IN library_files REMOVE file IN library_files")

    def batch_upsert_library_files(self, files: list[dict[str, Any]]) -> None:
        """Insert or update multiple library files.

        Args:
            files: List of file dicts with keys:
                - path (str)
                - library_id (int)
                - metadata (dict)
                - file_size (int)
                - modified_time (int)
                - needs_tagging (bool)
                - is_valid (bool)
                - scanned_at (int)
        """
        for file_data in files:
            metadata = file_data.get("metadata", {})
            self.db.aql.execute(
                """
                UPSERT { library_id: @library_id, path: @path }
                INSERT {
                    library_id: @library_id,
                    path: @path,
                    file_size: @file_size,
                    modified_time: @modified_time,
                    duration_seconds: @duration,
                    artist: @artist,
                    album: @album,
                    title: @title,
                    needs_tagging: @needs_tagging,
                    is_valid: @is_valid,
                    scanned_at: @scanned_at,
                    tagged: 0,
                    chromaprint: null,
                    calibration: {}
                }
                UPDATE {
                    file_size: @file_size,
                    modified_time: @modified_time,
                    duration_seconds: @duration,
                    artist: @artist,
                    album: @album,
                    title: @title,
                    needs_tagging: @needs_tagging,
                    is_valid: @is_valid,
                    scanned_at: @scanned_at
                }
                IN library_files
                """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "library_id": file_data["library_id"],
                        "path": file_data["path"],
                        "file_size": file_data["file_size"],
                        "modified_time": file_data["modified_time"],
                        "duration": metadata.get("duration"),
                        "artist": metadata.get("artist"),
                        "album": metadata.get("album"),
                        "title": metadata.get("title"),
                        "needs_tagging": int(file_data["needs_tagging"]),
                        "is_valid": int(file_data["is_valid"]),
                        "scanned_at": file_data["scanned_at"],
                    },
                ),
            )

    def mark_file_invalid(self, path: str) -> None:
        """Mark file as no longer existing on disk.

        Args:
            path: File path to mark invalid
        """
        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path == @path
                UPDATE file WITH { is_valid: 0 } IN library_files
            """,
            bind_vars={"path": path},
        )

    def bulk_mark_invalid(self, paths: list[str]) -> None:
        """Mark multiple files as invalid.

        Args:
            paths: List of file paths to mark invalid
        """
        if not paths:
            return

        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path IN @paths
                UPDATE file WITH { is_valid: 0 } IN library_files
            """,
            bind_vars={"paths": paths},
        )

    def update_file_path(
        self,
        file_id: str,
        new_path: str,
        file_size: int,
        modified_time: int,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        """Update file path and metadata (for moved files).

        Updates filesystem and metadata fields but preserves ML tags.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            new_path: New file path
            file_size: File size in bytes
            modified_time: Last modified timestamp
            artist: Artist name (optional)
            album: Album name (optional)
            title: Track title (optional)
            duration_seconds: Duration in seconds (optional)
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                path: @new_path,
                file_size: @file_size,
                modified_time: @modified_time,
                is_valid: 1,
                artist: @artist,
                album: @album,
                title: @title,
                duration_seconds: @duration_seconds,
                scanned_at: @scanned_at
            } IN library_files
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "file_id": file_id,
                    "new_path": new_path,
                    "file_size": file_size,
                    "modified_time": modified_time,
                    "artist": artist,
                    "album": album,
                    "title": title,
                    "duration_seconds": duration_seconds,
                    "scanned_at": now_ms(),
                },
            ),
        )

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if library has any files with ML tags.

        Args:
            library_id: Library ID

        Returns:
            True if library has at least one tagged file
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.library_id == @library_id AND file.tagged == 1
                SORT file._key
                LIMIT 1
                RETURN 1
            """,
                bind_vars=cast(dict[str, Any], {"library_id": library_id}),
            ),
        )
        result = list(cursor)
        return len(result) > 0

    def get_files_needing_tagging(self, library_id: int | None, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Get files that need ML tagging.

        Args:
            library_id: Library ID (or None for all libraries)
            paths: Optional specific file paths to filter

        Returns:
            List of file dicts needing tagging
        """
        filters = ["file.needs_tagging == 1", "file.is_valid == 1"]
        bind_vars: dict[str, Any] = {}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        if paths:
            filters.append("file.path IN @paths")
            bind_vars["paths"] = paths

        filter_clause = " AND ".join(filters)

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                FILTER {filter_clause}
                RETURN file
            """,
                bind_vars=bind_vars,
            ),
        )
        return list(cursor)

    def get_files_by_chromaprint(self, chromaprint: str, library_id: int | None = None) -> list[dict[str, Any]]:
        """Get library files matching a chromaprint (for move detection).

        Args:
            chromaprint: Audio fingerprint hash to search for
            library_id: Optional library ID to restrict search

        Returns:
            List of file dicts with matching chromaprint
        """
        filters = ["file.chromaprint == @chromaprint"]
        bind_vars: dict[str, Any] = {"chromaprint": chromaprint}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        filter_clause = " AND ".join(filters)

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                FILTER {filter_clause}
                RETURN file
            """,
                bind_vars=bind_vars,
            ),
        )
        return list(cursor)

    def set_chromaprint(self, file_id: str, chromaprint: str) -> None:
        """Set chromaprint for a file.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            chromaprint: Audio fingerprint hash
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                chromaprint: @chromaprint
            } IN library_files
            """,
            bind_vars={"file_id": file_id, "chromaprint": chromaprint},
        )

    def update_calibration(self, file_id: str, calibration: dict[str, Any]) -> None:
        """Update calibration metadata for a file.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            calibration: Calibration metadata dict
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                calibration: @calibration
            } IN library_files
            """,
            bind_vars={"file_id": file_id, "calibration": calibration},
        )

    def get_artist_album_frequencies(self, limit: int) -> dict[str, list[tuple[str, int]]]:
        """Get artist and album frequency data for analytics.

        Returns:
            Dict with keys: artist_rows, album_rows (each is list of (name, count) tuples)
        """
        # Count artists
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.artist != null
                COLLECT artist = file.artist WITH COUNT INTO count
                SORT count DESC
                LIMIT @limit
                RETURN [artist, count]
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        artist_rows = [tuple(row) for row in cursor]

        # Count albums
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.album != null
                COLLECT album = file.album WITH COUNT INTO count
                SORT count DESC
                LIMIT @limit
                RETURN [album, count]
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        album_rows = [tuple(row) for row in cursor]

        return {
            "artist_rows": artist_rows,
            "album_rows": album_rows,
        }

    def get_tracks_by_file_ids(
        self,
        file_ids: set[str],
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch track metadata for given file IDs.

        Args:
            file_ids: Set of file _ids to fetch
            order_by: List of (column, direction) tuples. If None, random order.
            limit: Maximum number of tracks to return

        Returns:
            List of track dicts with path, title, artist, album
        """
        from pathlib import Path

        if not file_ids:
            return []

        # Build ORDER BY clause
        if order_by:
            sort_parts = [f"file.{col} {dir.upper()}" for col, dir in order_by]
            sort_clause = f"SORT {', '.join(sort_parts)}"
        else:
            sort_clause = "SORT RAND()"  # Random sampling for preview

        limit_clause = f"LIMIT {limit}" if limit else ""

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                FILTER file._id IN @file_ids
                {sort_clause}
                {limit_clause}
                RETURN {{
                    path: file.path,
                    title: file.title,
                    artist: file.artist,
                    album: file.album
                }}
            """,
                bind_vars=cast(dict[str, Any], {"file_ids": list(file_ids)}),
            ),
        )

        results = []
        for row in cursor:
            results.append(
                {
                    "path": row["path"],
                    "title": row["title"] if row["title"] else Path(row["path"]).stem,
                    "artist": row["artist"] if row["artist"] else "Unknown Artist",
                    "album": row["album"] if row["album"] else "Unknown Album",
                }
            )

        return results

    def search_library_files_with_tags(
        self,
        q: str = "",
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
            q: Text search query for artist/album/title
            artist: Filter by artist name
            album: Filter by album name
            tag_key: Filter by files that have this tag key
            tag_value: Filter by specific tag key=value (requires tag_key)
            tagged_only: Only return tagged files
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            Tuple of (files list with tags, total count)
        """
        # Build filter conditions
        filters = []

        if tag_key and tag_value:
            filters.append(
                """
            LENGTH(
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.file_id == file._id 
                            AND ft.tag_id == lt._id
                            AND lt.key == @tag_key 
                            AND lt.value == @tag_value
                        SORT ft._key
                        LIMIT 1
                        RETURN 1
            ) > 0
            """
            )
        elif tag_key:
            filters.append(
                """
            LENGTH(
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.file_id == file._id 
                            AND ft.tag_id == lt._id
                            AND lt.key == @tag_key
                        SORT ft._key
                        LIMIT 1
                        RETURN 1
            ) > 0
            """
            )

        if q:
            filters.append(
                "(LIKE(file.artist, @q_pattern, true) OR LIKE(file.album, @q_pattern, true) OR LIKE(file.title, @q_pattern, true))"
            )

        if artist:
            filters.append("file.artist == @artist")

        if album:
            filters.append("file.album == @album")

        if tagged_only:
            filters.append("file.tagged == 1")

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        bind_vars: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if tag_key:
            bind_vars["tag_key"] = tag_key
        if tag_value:
            bind_vars["tag_value"] = tag_value
        if q:
            bind_vars["q_pattern"] = f"%{q}%"
        if artist:
            bind_vars["artist"] = artist
        if album:
            bind_vars["album"] = album

        # Get total count
        count_cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )
        total = next(count_cursor, 0)

        # Get files with tags
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                SORT file.artist, file.album, file.title
                LIMIT @offset, @limit
                LET tags = (
                    FOR ft IN file_tags
                        FILTER ft.file_id == file._id
                        FOR lt IN library_tags
                            FILTER ft.tag_id == lt._id
                            SORT lt.key
                            RETURN {{
                                key: lt.key,
                                value: lt.value,
                                is_nomarr: lt.is_nomarr_tag
                            }}
                )
                RETURN MERGE(file, {{ tags: tags }})
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )

        return list(cursor), total
