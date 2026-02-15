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
                "title": row["title"] if row["title"] else Path(row["path"]).stem,
                "artist": row["artist"] if row["artist"] else "Unknown Artist",
                "album": row["album"] if row["album"] else "Unknown Album",
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
            library_id: Optional library _id to filter by.

        Returns:
            List of dicts with _id, path, title, artist, album, isrc fields.

        """
        library_filter = ""
        bind_vars: dict[str, Any] = {}

        if library_id:
            library_filter = "FILTER f.library_id == @library_id"
            bind_vars["library_id"] = library_id

        # Query files and LEFT JOIN with tags to get ISRC if available
        query = f"""
        FOR f IN library_files
            FILTER f.is_valid == true
            {library_filter}

            // Left join to get ISRC from tags
            LET isrc_tag = FIRST(
                FOR e IN song_tag_edges
                    FILTER e._from == f._id
                    FOR t IN tags
                        FILTER t._id == e._to
                        FILTER t.rel == "isrc"
                        RETURN t.value
            )

            RETURN {{
                _id: f._id,
                path: f.path,
                title: f.title,
                artist: f.artist,
                album: f.album,
                isrc: isrc_tag
            }}
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=bind_vars))
        return list(cursor)
