"""Track operations for library_files collection."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesTracksMixin:
    """Track operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

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
            "Cursor",
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
                bind_vars=cast("dict[str, Any]", {"file_ids": list(file_ids)}),
            ),
        )

        return [
            {
                "path": row["path"],
                "title": row["title"] or Path(row["path"]).stem,
                "artist": row["artist"] or "Unknown Artist",
                "album": row["album"] or "Unknown Album",
            }
            for row in cursor
        ]

    def get_tracks_for_matching(
        self,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all tracks with metadata for playlist matching.

        Returns tracks with essential metadata for fuzzy matching:
        _id, path, title, artist, album.

        ISRC is retrieved from tags collection if available.

        Args:
            library_id: Optional library ``_id`` to filter by; uses OUTBOUND
                edge traversal on ``library_contains_file``.

        Returns:
            List of dicts with _id, path, title, artist, album, isrc fields.

        """
        bind_vars: dict[str, Any] = {}

        if library_id:
            bind_vars["library_id"] = library_id
            query = """
            FOR f IN OUTBOUND @library_id library_contains_file
                FILTER f.is_valid == true

                // Left join to get ISRC from tags
                LET isrc_tag = FIRST(
                    FOR e IN song_has_tags
                        FILTER e._from == f._id
                        FOR t IN tags
                            FILTER t._id == e._to
                            FILTER t.rel == "isrc"
                            RETURN t.value
                )

                RETURN {
                    _id: f._id,
                    path: f.path,
                    title: f.title,
                    artist: f.artist,
                    album: f.album,
                    isrc: isrc_tag
                }
            """
        else:
            query = """
            FOR f IN library_files
                FILTER f.is_valid == true

                // Left join to get ISRC from tags
                LET isrc_tag = FIRST(
                    FOR e IN song_has_tags
                        FILTER e._from == f._id
                        FOR t IN tags
                            FILTER t._id == e._to
                            FILTER t.rel == "isrc"
                            RETURN t.value
                )

                RETURN {
                    _id: f._id,
                    path: f.path,
                    title: f.title,
                    artist: f.artist,
                    album: f.album,
                    isrc: isrc_tag
                }
            """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=bind_vars))
        return list(cursor)
