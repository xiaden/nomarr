"""Statistics operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesStatsMixin:
    """Statistics operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

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
            "Cursor",
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
                    needs_tagging_count = SUM(file.needs_tagging == true ? 1 : 0)
                RETURN {{
                    total_files,
                    total_artists,
                    total_albums,
                    total_duration,
                    total_size,
                    needs_tagging_count
                }}
            """,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        result: dict[str, Any] = next(cursor, {})
        return result

    def get_library_counts(self) -> dict[str, dict[str, int]]:
        """Get file and folder counts for all libraries.

        Returns:
            Dict mapping library_id to {"file_count": int, "folder_count": int}
            Only includes valid files (is_valid == true or 1).

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR file IN library_files
                    FILTER file.is_valid == true
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
                """,
            ),
        )

        result: dict[str, dict[str, int]] = {}
        for row in cursor:
            lib_id = row["library_id"]
            result[lib_id] = {"file_count": row["file_count"], "folder_count": row["folder_count"]}
        return result

    def count_files_with_tags(self, namespace: str = "nom") -> int:
        """Count total files with tags in the given namespace.

        Args:
            namespace: Tag namespace (default "nom")

        Returns:
            Total count of files with at least one tag in namespace

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                RETURN LENGTH(
                  FOR edge IN song_tag_edges
                    LET tag = DOCUMENT(edge._to)
                    FILTER STARTS_WITH(tag.rel, CONCAT(@namespace, ":"))
                    COLLECT file_id = edge._from
                    RETURN 1
                )
                """,
                bind_vars=cast("dict[str, Any]", {"namespace": namespace}),
            ),
        )
        result = next(cursor, 0)
        return int(result)

    def get_artist_album_frequencies(self, limit: int) -> dict[str, list[tuple[str, int]]]:
        """Get artist and album frequency data for analytics.

        Returns:
            Dict with keys: artist_rows, album_rows (each is list of (name, count) tuples)

        """
        # Count artists
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.artist != null
                COLLECT artist = file.artist WITH COUNT INTO count
                SORT count DESC
                LIMIT @limit
                RETURN [artist, count]
            """,
                bind_vars=cast("dict[str, Any]", {"limit": limit}),
            ),
        )
        artist_rows = [tuple(row) for row in cursor]

        # Count albums
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.album != null
                COLLECT album = file.album WITH COUNT INTO count
                SORT count DESC
                LIMIT @limit
                RETURN [album, count]
            """,
                bind_vars=cast("dict[str, Any]", {"limit": limit}),
            ),
        )
        album_rows = [tuple(row) for row in cursor]

        return {"artist_rows": artist_rows, "album_rows": album_rows}

    def clear_library_data(self) -> None:
        """Clear all library files and song_tag_edges.

        WARNING: This is a cross-collection operation that deletes from:
        - song_tag_edges
        - library_files
        """
        # Truncate vectors_track collections first (derived data — per-backbone)
        for coll_info in self.db.collections():  # type: ignore[union-attr]
            coll_name = coll_info["name"]
            if coll_name.startswith("vectors_track__"):
                self.db.collection(coll_name).truncate()
        # Delete segment_scores_stats (derived data)
        self.db.aql.execute("FOR doc IN segment_scores_stats REMOVE doc IN segment_scores_stats")
        # Delete song_tag_edges (edge collection)
        self.db.aql.execute("FOR edge IN song_tag_edges REMOVE edge IN song_tag_edges")
        # Delete library_files
        self.db.aql.execute("FOR file IN library_files REMOVE file IN library_files")

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
                "Cursor",
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
                                    type: IS_NUMBER(t2.value) ? "float" : "string",
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
                        "dict[str, Any]",
                        {"tag_key": tag_key, "target_value": float(target_value), "limit": limit, "offset": offset},
                    ),
                ),
            )
        else:
            # String: exact match
            cursor = cast(
                "Cursor",
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
                                    type: IS_NUMBER(t2.value) ? "float" : "string",
                                    is_nomarr: STARTS_WITH(t2.rel, "nom:")
                                }
                        )

                        RETURN MERGE(file, {
                            tags: all_tags,
                            matched_tag: { key: @tag_key, value: @target_value }
                        })
                """,
                    bind_vars=cast(
                        "dict[str, Any]",
                        {"tag_key": tag_key, "target_value": str(target_value), "limit": limit, "offset": offset},
                    ),
                ),
            )
        return list(cursor)
