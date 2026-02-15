"""Analytics operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor


logger = logging.getLogger(__name__)


class TagAnalyticsMixin:
    """Analytics operations for tags."""

    db: Any
    collection: Any

    def get_year_distribution(self, library_id: str | None = None) -> list[dict[str, Any]]:
        """Get year/decade distribution for Collection Overview.

        Args:
            library_id: Optional library _id to filter by.
                        If None, returns stats for all libraries.

        Returns:
            List of {year: int, count: int} sorted by count descending.

        """
        library_filter = ""
        bind_vars: dict[str, Any] = {}

        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars["library_id"] = library_id

        query = f"""
        FOR tag IN tags
            FILTER tag.rel == "year"
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN 1
            )
            FILTER song_count > 0
            SORT song_count DESC
            RETURN {{
                year: tag.value,
                count: song_count
            }}
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def get_genre_distribution(
        self,
        library_id: str | None = None,
        limit: int | None = 20,
    ) -> list[dict[str, Any]]:
        """Get genre distribution for Collection Overview.

        Args:
            library_id: Optional library _id to filter by.
            limit: Max genres to return (sorted by count desc). None = no limit.

        Returns:
            List of {genre: str, count: int} sorted by count descending.

        """
        library_filter = ""
        bind_vars: dict[str, Any] = {}
        limit_clause = ""

        if limit is not None:
            limit_clause = "LIMIT @limit"
            bind_vars["limit"] = limit

        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars["library_id"] = library_id

        query = f"""
        FOR tag IN tags
            FILTER tag.rel == "genre"
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN 1
            )
            FILTER song_count > 0
            SORT song_count DESC
            {limit_clause}
            RETURN {{
                genre: tag.value,
                count: song_count
            }}
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)
