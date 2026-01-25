"""Library files operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

from typing import Any, Literal, cast

from arango.cursor import Cursor

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike


class LibraryFilesOperations:
    """Operations for the library_files collection."""

    def __init__(self, db: DatabaseLike) -> None:
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
        last_tagged_at: int | None = None,
        has_nomarr_namespace: bool | None = None,
        last_written_mode: str | None = None,
    ) -> str:
        """Insert or update a library file entry.

        Note: calibration_hash field remains NULL until first recalibration.
        Initial processing stores raw scores only.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            library_id: ID of owning library
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            last_tagged_at: Last tagging timestamp
            has_nomarr_namespace: Whether file has nomarr tags in audio file
            last_written_mode: Inferred write mode from existing file tags

        Returns:
            Document _id (e.g., "library_files/12345")

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot upsert invalid path ({path.status}): {path.reason}")

        scanned_at = now_ms().value
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
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at,
                tagged: 0,
                tagged_version: null,
                chromaprint: null,
                calibration_hash: null,
                needs_tagging: 1,
                is_valid: 1,
                // Tag writing projection state fields
                last_written_mode: @last_written_mode,
                last_written_calibration_hash: null,
                last_written_at: null,
                has_nomarr_namespace: @has_nomarr_namespace == null ? false : @has_nomarr_namespace,
                write_claimed_by: null,
                write_claimed_at: null
            }
            UPDATE {
                library_id: @library_id,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at != null ? @last_tagged_at : OLD.last_tagged_at,
                has_nomarr_namespace: @has_nomarr_namespace != null ? @has_nomarr_namespace : OLD.has_nomarr_namespace,
                last_written_mode: @last_written_mode != null ? @last_written_mode : OLD.last_written_mode
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
                        "scanned_at": scanned_at,
                        "last_tagged_at": last_tagged_at,
                        "has_nomarr_namespace": has_nomarr_namespace,
                        "last_written_mode": last_written_mode,
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
            bind_vars=cast(
                dict[str, Any], {"file_id": file_id, "version": tagged_version, "timestamp": now_ms().value}
            ),
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

    def get_files_by_ids_with_tags(
        self,
        file_ids: list[str],
    ) -> list[dict[str, Any]]:
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
            Cursor,
            self.db.aql.execute(
                """
            FOR file_id IN @file_ids
                LET file = DOCUMENT(file_id)
                FILTER file != null
                LET tags = (
                    FOR edge IN song_tag_edges
                        FILTER edge._from == file._id
                        LET tag = DOCUMENT(edge._to)
                        FILTER tag != null
                        RETURN {
                            key: tag.rel,
                            value: tag.value,
                            type: "string",
                            is_nomarr: STARTS_WITH(tag.rel, "nom:")
                        }
                )
                RETURN MERGE(file, { tags: tags })
            """,
                bind_vars=cast(dict[str, Any], {"file_ids": file_ids}),
            ),
        )
        return list(cursor)

    def search_files_by_tag(
        self,
        tag_key: str,
        target_value: float | str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search files by tag value with distance sorting (float) or exact match (string).

        For float values: Returns files sorted by absolute distance from target value.
        For string values: Returns files with exact match on the tag value.

        Args:
            tag_key: Tag rel to search (e.g., "nom:bpm", "genre")
            target_value: Target value (float for distance sort, string for exact match)
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of file dicts with 'tags' array, 'matched_tag', and 'distance' (for floats)
        """
        is_float = isinstance(target_value, float | int) and not isinstance(target_value, bool)

        if is_float:
            # Float: search by distance
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR tag IN tags
                    FILTER tag.rel == @tag_key
                    FILTER IS_NUMBER(tag.value)
                    LET distance = ABS(tag.value - @target_value)

                    // Find files with this tag
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LET file = DOCUMENT(edge._from)
                        FILTER file != null

                        SORT distance ASC
                        LIMIT @offset, @limit

                        // Get all tags for the file
                        LET all_tags = (
                            FOR e2 IN song_tag_edges
                                FILTER e2._from == file._id
                                LET t2 = DOCUMENT(e2._to)
                                FILTER t2 != null
                                RETURN {
                                    key: t2.rel,
                                    value: t2.value,
                                    is_nomarr: STARTS_WITH(t2.rel, "nom:")
                                }
                        )

                        RETURN MERGE(file, {
                            tags: all_tags,
                            matched_tag: { key: @tag_key, value: tag.value },
                            distance: distance
                        })
                """,
                    bind_vars=cast(
                        dict[str, Any],
                        {
                            "tag_key": tag_key,
                            "target_value": float(target_value),
                            "limit": limit,
                            "offset": offset,
                        },
                    ),
                ),
            )
        else:
            # String: exact match
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR tag IN tags
                    FILTER tag.rel == @tag_key AND tag.value == @target_value

                    // Find files with this tag
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LET file = DOCUMENT(edge._from)
                        FILTER file != null

                        SORT file.artist, file.album, file.title
                        LIMIT @offset, @limit

                        // Get all tags for the file
                        LET all_tags = (
                            FOR e2 IN song_tag_edges
                                FILTER e2._from == file._id
                                LET t2 = DOCUMENT(e2._to)
                                FILTER t2 != null
                                RETURN {
                                    key: t2.rel,
                                    value: t2.value,
                                    is_nomarr: STARTS_WITH(t2.rel, "nom:")
                                }
                        )

                        RETURN MERGE(file, {
                            tags: all_tags,
                            matched_tag: { key: @tag_key, value: @target_value }
                        })
                """,
                    bind_vars=cast(
                        dict[str, Any],
                        {
                            "tag_key": tag_key,
                            "target_value": str(target_value),
                            "limit": limit,
                            "offset": offset,
                        },
                    ),
                ),
            )
        return list(cursor)

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

        if library_id is not None:
            filters.append("file.library_id == @library_id")

        if artist:
            filters.append("file.artist == @artist")

        if album:
            filters.append("file.album == @album")

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        # Build bind_vars for filter conditions (used by count query)
        filter_bind_vars: dict[str, Any] = {}
        if library_id is not None:
            filter_bind_vars["library_id"] = library_id
        if artist:
            filter_bind_vars["artist"] = artist
        if album:
            filter_bind_vars["album"] = album

        # Get total count (only needs filter bind vars)
        count_query = f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
        """
        count_cursor = cast(Cursor, self.db.aql.execute(count_query, bind_vars=filter_bind_vars))
        total = next(count_cursor, 0)

        # Get paginated results (needs filter + pagination bind vars)
        paginated_bind_vars = {**filter_bind_vars, "limit": limit, "offset": offset}
        query = f"""
            FOR file IN library_files
                {filter_clause}
                SORT file.artist, file.album, file.title
                LIMIT @offset, @limit
                RETURN file
        """
        cursor = cast(Cursor, self.db.aql.execute(query, bind_vars=paginated_bind_vars))
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
        """Remove a file from the library and clean up entity edges.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
        """
        # Delete entity edges first (referential integrity)
        self.db.aql.execute(
            """
            FOR edge IN song_tag_edges
                FILTER edge._to == @file_id
                REMOVE edge IN song_tag_edges
            """,
            bind_vars={"file_id": file_id},
        )

        # Then delete the file
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
            Dict with: total_files, total_artists, total_albums, total_duration, total_size,
                       needs_tagging_count (files awaiting processing)
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
                    total_size = SUM(file.file_size),
                    needs_tagging_count = SUM(file.needs_tagging == 1 ? 1 : 0)
                RETURN {{
                    total_files,
                    total_artists,
                    total_albums,
                    total_duration,
                    total_size,
                    needs_tagging_count
                }}
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )
        result: dict[str, Any] = next(cursor, {})
        return result

    def clear_library_data(self) -> None:
        """Clear all library files and song_tag_edges.

        WARNING: This is a cross-collection operation that deletes from:
        - song_tag_edges
        - library_files
        """
        # Delete song_tag_edges first (edge collection)
        self.db.aql.execute("FOR edge IN song_tag_edges REMOVE edge IN song_tag_edges")
        # Delete library_files
        self.db.aql.execute("FOR file IN library_files REMOVE file IN library_files")

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
                    "scanned_at": now_ms().value,
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

    def discover_next_unprocessed_file(self) -> dict[str, Any] | None:
        """Discover next file needing ML tagging for worker discovery.

        Query optimized for discovery-based workers:
        - Filters: needs_tagging=1, is_valid=1
        - Deterministic ordering by _key for consistent work distribution
        - LIMIT 1 for single-file claiming

        Returns:
            File dict or None if no work available
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR file IN library_files
                    FILTER file.needs_tagging == 1
                    FILTER file.is_valid == 1
                    SORT file._key
                    LIMIT 1
                    RETURN file
                """
            ),
        )
        return next(iter(cursor), None)

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

    def update_calibration_hash(self, file_id: str, calibration_hash: str) -> None:
        """Update the calibration version hash for a file.

        CALIBRATION_HASH SEMANTICS:
        - NULL: File never recalibrated (initial processing with raw scores)
        - Hash value: MD5 of all calibration_state.calibration_def_hash values
          at the time this file's mood tags were last computed via recalibration

        Used to determine if recalibration is needed by comparing against
        meta.calibration_version (current global hash).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            calibration_hash: Global calibration version hash from meta collection
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                calibration_hash: @calibration_hash
            } IN library_files
            """,
            bind_vars={"file_id": file_id, "calibration_hash": calibration_hash},
        )

    def get_calibration_status_by_library(self, expected_hash: str) -> list[dict[str, Any]]:
        """Get calibration status counts grouped by library.

        Returns count of files with current calibration hash vs outdated/missing.

        Args:
            expected_hash: Expected global calibration version hash

        Returns:
            List of {library_id, total_files, current_count, outdated_count}
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR f IN library_files
                    COLLECT lib_id = f.library_id
                    AGGREGATE
                        total = COUNT(1),
                        current = SUM(f.calibration_hash == @expected_hash ? 1 : 0)
                    LET outdated = total - current
                    RETURN {
                        library_id: lib_id,
                        total_files: total,
                        current_count: current,
                        outdated_count: outdated
                    }
                """,
                bind_vars=cast(dict[str, Any], {"expected_hash": expected_hash}),
            ),
        )
        return list(cursor)

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
            tag_key: Filter by files that have this tag key (rel)
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
                FOR edge IN song_tag_edges
                    FILTER edge._from == file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == @tag_key AND tag.value == @tag_value
                    LIMIT 1
                    RETURN 1
            ) > 0
            """
            )
        elif tag_key:
            filters.append(
                """
            LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._from == file._id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == @tag_key
                    LIMIT 1
                    RETURN 1
            ) > 0
            """
            )

        if q:
            filters.append(
                "(LIKE(file.artist, @q_pattern, true) OR "
                "LIKE(file.album, @q_pattern, true) OR "
                "LIKE(file.title, @q_pattern, true))"
            )

        if artist:
            filters.append("file.artist == @artist")

        if album:
            filters.append("file.album == @album")

        if tagged_only:
            filters.append("file.tagged == 1")

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        # Build filter-only bind vars (for count query)
        filter_bind_vars: dict[str, Any] = {}
        if tag_key:
            filter_bind_vars["tag_key"] = tag_key
        if tag_value:
            filter_bind_vars["tag_value"] = tag_value
        if q:
            filter_bind_vars["q_pattern"] = f"%{q}%"
        if artist:
            filter_bind_vars["artist"] = artist
        if album:
            filter_bind_vars["album"] = album

        # Get total count (without limit/offset)
        count_cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast(dict[str, Any], filter_bind_vars),
            ),
        )
        total = next(count_cursor, 0)

        # Build full bind vars (with pagination) for data query
        bind_vars = {**filter_bind_vars, "limit": limit, "offset": offset}

        # Get files with tags (using unified schema)
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                {filter_clause}
                SORT file.artist, file.album, file.title
                LIMIT @offset, @limit
                LET tags = (
                    FOR edge IN song_tag_edges
                        FILTER edge._from == file._id
                        LET tag = DOCUMENT(edge._to)
                        FILTER tag != null
                        SORT tag.rel
                        RETURN {{
                            key: tag.rel,
                            value: tag.value,
                            is_nomarr: STARTS_WITH(tag.rel, "nom:")
                        }}
                )
                RETURN MERGE(file, {{ tags: tags }})
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )

        return list(cursor), total

    def upsert_batch(self, file_docs: list[dict[str, Any]]) -> int:
        """Batch upsert file documents to ArangoDB.

        More efficient than individual upserts - reduces DB roundtrips.
        Uses (library_id, normalized_path) as unique key for upsert logic.

        Args:
            file_docs: List of file documents. Each must have:
                - library_id: Library document _id
                - normalized_path: POSIX-style path relative to library root
                - Other fields as needed (file_size, modified_time, etc.)

        Returns:
            Number of documents processed

        Note: ArangoDB UPSERT does not reliably distinguish inserted vs updated.
        Workflows must not depend on this split for correctness.
        """
        if not file_docs:
            return 0

        # Use AQL UPSERT for atomic insert-or-update
        # Key on (library_id, normalized_path) tuple
        self.db.aql.execute(
            """
            FOR doc IN @docs
                UPSERT {
                    library_id: doc.library_id,
                    normalized_path: doc.normalized_path
                }
                INSERT doc
                UPDATE doc
                IN library_files
            """,
            bind_vars={"docs": file_docs},
        )

        return len(file_docs)

    def mark_missing_for_library(self, library_id: str, scan_id: str) -> int:
        """Mark files not seen in this scan as invalid.

        Args:
            library_id: Library that was scanned (full scan only)
            scan_id: Identifier of this scan (timestamp or unique ID)

        Returns:
            Number of files marked invalid

        Files with last_seen_scan_id != scan_id are assumed deleted.
        Only call this for FULL library scans (not targeted scans).
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR file IN library_files
                    FILTER file.library_id == @library_id
                    FILTER file.last_seen_scan_id != @scan_id
                    FILTER file.is_valid == 1
                    UPDATE file WITH { is_valid: 0 } IN library_files
                    COLLECT WITH COUNT INTO marked
                    RETURN marked
                """,
                bind_vars={
                    "library_id": library_id,
                    "scan_id": scan_id,
                },
            ),
        )

        results = list(cursor)
        return results[0] if results else 0

    def get_library_counts(self) -> dict[str, dict[str, int]]:
        """Get file and folder counts for all libraries.

        Returns:
            Dict mapping library_id to {"file_count": int, "folder_count": int}
            Only includes valid files (is_valid == true or 1).
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR file IN library_files
                    FILTER file.is_valid == true OR file.is_valid == 1
                    COLLECT library_id = file.library_id
                    AGGREGATE
                        file_count = COUNT(1),
                        folders = UNIQUE(
                            REGEX_REPLACE(file.path, '/[^/]+$', '')
                        )
                    RETURN {
                        library_id: library_id,
                        file_count: file_count,
                        folder_count: LENGTH(folders)
                    }
                """
            ),
        )

        result: dict[str, dict[str, int]] = {}
        for row in cursor:
            lib_id = row["library_id"]
            result[lib_id] = {
                "file_count": row["file_count"],
                "folder_count": row["folder_count"],
            }
        return result

    # ──────────────────────────────────────────────────────────────────────
    # Tag Writing Reconciliation Methods
    # ──────────────────────────────────────────────────────────────────────

    def claim_files_for_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
        worker_id: str,
        batch_size: int = 100,
        lease_ms: int = 60000,
    ) -> list[dict[str, Any]]:
        """Atomically claim files that need tag reconciliation.

        Files need reconciliation when:
        - last_written_mode != target_mode (mode mismatch)
        - calibration_hash mismatch for modes using mood tags (minimal, full)
        - has_nomarr_namespace = true but never tracked (bootstrap case)

        Claims are released after lease_ms expires (stale claim recovery).

        Args:
            library_id: Library document _id
            target_mode: Desired write mode ("none", "minimal", "full")
            calibration_hash: Current calibration hash (None if no calibration)
            worker_id: Worker claiming the files
            batch_size: Max files to claim
            lease_ms: Claim lease duration in milliseconds

        Returns:
            List of claimed file documents
        """
        now = now_ms().value
        lease_expiry = now - lease_ms

        # Build mismatch conditions
        # Mode mismatch: recorded mode differs from target
        # Calibration mismatch: applies only when target uses mood tags
        # Bootstrap: has namespace but never tracked
        calibration_condition = ""
        if calibration_hash and target_mode in ("minimal", "full"):
            calibration_condition = """
                OR (f.last_written_calibration_hash != @calibration_hash)
            """

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
                LET now = @now
                LET lease_expiry = @lease_expiry

                FOR f IN library_files
                    FILTER f.library_id == @library_id
                    FILTER f.is_valid == 1
                    FILTER f.tagged == 1  // Only reconcile files with ML tags

                    // Unclaimed or stale claim
                    FILTER f.write_claimed_by == null
                        OR f.write_claimed_at < lease_expiry

                    // Mismatch conditions (needs reconciliation)
                    FILTER (
                        // Mode mismatch
                        f.last_written_mode != @target_mode

                        // Calibration mismatch (only for modes using mood tags)
                        {calibration_condition}

                        // Bootstrap: namespace exists but never tracked
                        OR (f.has_nomarr_namespace == true AND f.last_written_mode == null)
                    )

                    SORT f._key
                    LIMIT @batch_size

                    // Atomically claim
                    UPDATE f WITH {{
                        write_claimed_by: @worker_id,
                        write_claimed_at: now
                    }} IN library_files

                    RETURN NEW
                """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "library_id": library_id,
                        "target_mode": target_mode,
                        "calibration_hash": calibration_hash,
                        "worker_id": worker_id,
                        "batch_size": batch_size,
                        "now": now,
                        "lease_expiry": lease_expiry,
                    },
                ),
            ),
        )
        return list(cursor)

    def set_file_written(
        self,
        file_key: str,
        mode: str,
        calibration_hash: str | None,
    ) -> None:
        """Update file projection state after successful tag write.

        Clears write claim and updates last_written_* fields.

        Args:
            file_key: Document _key or _id
            mode: Write mode used ("none", "minimal", "full")
            calibration_hash: Calibration hash at time of write
        """
        # Normalize to just _key if full _id provided
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                last_written_mode: @mode,
                last_written_calibration_hash: @calibration_hash,
                last_written_at: @timestamp,
                write_claimed_by: null,
                write_claimed_at: null
            } IN library_files
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "file_key": file_key,
                    "mode": mode,
                    "calibration_hash": calibration_hash,
                    "timestamp": now_ms().value,
                },
            ),
        )

    def release_claim(self, file_key: str) -> None:
        """Release a write claim without updating projection state.

        Used when write fails - file remains mismatched for retry.

        Args:
            file_key: Document _key or _id
        """
        # Normalize to just _key if full _id provided
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                write_claimed_by: null,
                write_claimed_at: null
            } IN library_files
            """,
            bind_vars={"file_key": file_key},
        )

    def count_files_needing_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
    ) -> int:
        """Count files that need tag reconciliation.

        Args:
            library_id: Library document _id
            target_mode: Desired write mode
            calibration_hash: Current calibration hash

        Returns:
            Number of files needing reconciliation
        """
        calibration_condition = ""
        if calibration_hash and target_mode in ("minimal", "full"):
            calibration_condition = """
                OR (f.last_written_calibration_hash != @calibration_hash)
            """

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
                FOR f IN library_files
                    FILTER f.library_id == @library_id
                    FILTER f.is_valid == 1
                    FILTER f.tagged == 1

                    FILTER (
                        f.last_written_mode != @target_mode
                        {calibration_condition}
                        OR (f.has_nomarr_namespace == true AND f.last_written_mode == null)
                    )

                    COLLECT WITH COUNT INTO count
                    RETURN count
                """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "library_id": library_id,
                        "target_mode": target_mode,
                        "calibration_hash": calibration_hash,
                    },
                ),
            ),
        )
        result = next(cursor, 0)
        return int(result) if result else 0

    def count_files_with_tags(self, namespace: str = "nom") -> int:
        """Count total files with tags in the given namespace.

        Args:
            namespace: Tag namespace (default "nom")

        Returns:
            Total count of files with at least one tag in namespace
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR edge IN song_tag_edges
                  LET tag = DOCUMENT(edge._to)
                  FILTER STARTS_WITH(tag.rel, CONCAT(@namespace, ":"))
                  COLLECT file_id = edge._from
                  RETURN 1
                """,
                bind_vars=cast(dict[str, Any], {"namespace": namespace}),
            ),
        )
        if cursor:
            results: list[Any] = list(cursor)
            return len(results)
        return 0

    def update_nomarr_namespace_flag(self, file_key: str, has_namespace: bool) -> None:
        """Update the has_nomarr_namespace flag during scanning.

        Args:
            file_key: Document _key or _id
            has_namespace: Whether file has essentia:* namespace tags
        """
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                has_nomarr_namespace: @has_namespace
            } IN library_files
            """,
            bind_vars={"file_key": file_key, "has_namespace": has_namespace},
        )

    def infer_last_written_mode(
        self,
        file_key: str,
        mode: str,
    ) -> None:
        """Infer and set last_written_mode from on-disk tag patterns during scan.

        Used during bootstrap to infer projection state from existing files.

        Args:
            file_key: Document _key or _id
            mode: Inferred mode ("none", "minimal", "full", "unknown")
        """
        if file_key.startswith("library_files/"):
            file_key = file_key.split("/")[1]

        self.db.aql.execute(
            """
            UPDATE @file_key WITH {
                last_written_mode: @mode
            } IN library_files
            """,
            bind_vars={"file_key": file_key, "mode": mode},
        )
