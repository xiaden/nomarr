"""Mixin for higher-level tag analytics and batch operations.

These methods were historically implemented inside individual component files
and moved here as part of the Tier 2 → Tier 3 facade migration. They are
accessed through the ``db.tags`` facade on ``Database``.

Requires the host class (``TagsAqlOperations``) to provide:
- ``self._db`` (a ``SafeDatabase``)
- ``self.COLLECTION``
- ``self.EDGE_COLLECTION``
- ``self.FILE_COLLECTION``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.tags_dataclass import Tag, TagValue

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.persistence.arango_client import SafeDatabase

    Document = dict[str, Any]


class TagAnalyticsOpsMixin:
    """Mixin for higher-level tag analytics and batch-set operations.

    Requires the host class to provide ``self._db``, ``self.COLLECTION``,
    ``self.EDGE_COLLECTION``, and ``self.FILE_COLLECTION``.
    """

    _db: SafeDatabase
    COLLECTION: str
    EDGE_COLLECTION: str
    FILE_COLLECTION: str

    # ------------------------------------------------------------------
    # Song tags
    # ------------------------------------------------------------------

    def get_song_tags(self, file_id: str, nomarr_only: bool = False) -> list[Tag]:
        """Return all tags for a file as a list of ``Tag`` dataclass objects.

        Args:
            file_id: File document ID.
            nomarr_only: When True, only return tags whose name starts with
                ``"nom:"``.

        Returns:
            List of ``Tag`` objects, one per distinct tag name on the file.
            Each ``Tag.values`` is a tuple of one or more ``TagValue`` scalars.
            Returns an empty list when the file has no tags.
        """
        from nomarr.persistence.aql import primitives

        # Build the AQL: traverse edges from file → tag documents
        bind_vars: dict[str, Any] = {
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
            "file_id": file_id,
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._from == @file_id",
            "    LET tag = DOCUMENT(edge._to)",
            "    FILTER tag != null",
        ]
        if nomarr_only:
            query_lines.append('    FILTER LIKE(tag.name, "nom:%", true)')
        query_lines.append("    RETURN DISTINCT { name: tag.name, value: tag.value }")

        rows = primitives.execute(self._db, "\n".join(query_lines), bind_vars)

        # Group by tag name (a file can have multiple values for the same name)
        grouped: dict[str, list[TagValue]] = {}
        for row in rows:
            name = str(row.get("name", ""))
            value = row.get("value")
            if not name or value is None:
                continue
            # Normalize value into TagValue (str | int | float | bool)
            if isinstance(value, str | int | float | bool):
                grouped.setdefault(name, []).append(value)
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, str | int | float | bool):
                        grouped.setdefault(name, []).append(v)

        return [Tag(name=n, values=tuple(vs)) for n, vs in sorted(grouped.items())]

    # ------------------------------------------------------------------
    # Batch set song tags
    # ------------------------------------------------------------------

    def set_song_tags_batch(self, tag_entries: list[dict[str, Any]]) -> None:
        """Batch-set tags for one or more files.

        Each entry in ``tag_entries`` should have at least ``"file_id"``
        and ``"tags"`` keys, where ``"tags"`` is a list of ``{name, value}``
        dicts.

        This replaces all existing tag edges for each file with the provided
        tag set, then cleans up orphaned tag documents.
        """
        if not tag_entries:
            return

        for entry in tag_entries:
            file_id = entry.get("file_id", entry.get("song_id"))
            tags_payload = entry.get("tags", [])
            if not file_id:
                continue

            # Use the existing replace_file_tags logic (from sibling TagEdgeOpsMixin)
            self.replace_file_tags(file_id, tags_payload)  # type: ignore[attr-defined]  # cross-mixin call

    # ------------------------------------------------------------------
    # Distinct tag values for files
    # ------------------------------------------------------------------

    def get_distinct_tag_values_for_files(
        self,
        file_ids: Sequence[str],
        tag_name: str,
    ) -> set[str]:
        """Return the set of distinct tag values for a tag name across files.

        Args:
            file_ids: File document IDs to query.
            tag_name: Tag name to filter by (e.g. ``"artist"``, ``"genre"``).

        Returns:
            Set of distinct string values for that tag across all given files.
        """
        if not file_ids:
            return set()

        from nomarr.persistence.aql import primitives

        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.name == @tag_name
                RETURN DISTINCT tag.value
            """,
            {
                "@edge_collection": self.EDGE_COLLECTION,
                "file_ids": list(file_ids),
                "tag_name": tag_name,
            },
        )
        return {str(r) for r in rows if r is not None}

    # ------------------------------------------------------------------
    # Tag values grouped by file
    # ------------------------------------------------------------------

    def get_tag_values_grouped_by_file(
        self,
        file_ids: Sequence[str],
        tag_name: str,
    ) -> dict[str, set[str]]:
        """Return tag values grouped by file ID.

        Args:
            file_ids: File document IDs to query.
            tag_name: Tag name to filter by (e.g. ``"artist"``, ``"genre"``).

        Returns:
            Dict mapping each file ID to a set of tag values for that tag name.
            Files with no matching tag are omitted from the result.
        """
        if not file_ids:
            return {}

        from nomarr.persistence.aql import primitives

        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @file_ids
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.name == @tag_name
                RETURN { file_id: edge._from, value: tag.value }
            """,
            {
                "@edge_collection": self.EDGE_COLLECTION,
                "file_ids": list(file_ids),
                "tag_name": tag_name,
            },
        )
        result: dict[str, set[str]] = {}
        for row in rows:
            fid = row.get("file_id")
            val = row.get("value")
            if fid is None or val is None:
                continue
            result.setdefault(str(fid), set()).add(str(val))
        return result

    # ------------------------------------------------------------------
    # Library stats
    # ------------------------------------------------------------------

    def get_library_stats(self, library_id: str | None = None) -> dict[str, Any]:
        """Return aggregate library statistics as a dict.

        Args:
            library_id: Optional library ``_id`` to scope the query. When
                ``None``, returns stats for all libraries.

        Returns:
            Dict with keys like ``file_count``, ``total_size``,
            ``total_duration``, etc.
        """
        from nomarr.persistence.aql import primitives

        bind_vars: dict[str, Any] = {
            "@file_collection": self.FILE_COLLECTION,
        }
        filters = ""
        if library_id is not None:
            filters = "FILTER doc.library_id == @library_id"
            bind_vars["library_id"] = library_id

        rows = primitives.execute(
            self._db,
            f"""
            FOR doc IN @@file_collection
                {filters}
                COLLECT AGGREGATE
                    file_count = COUNT(doc),
                    total_size = SUM(doc.size OR 0),
                    total_duration = SUM(doc.duration OR 0)
                RETURN {{
                    file_count: file_count,
                    total_size: total_size,
                    total_duration: total_duration
                }}
            """,
            bind_vars,
        )
        if rows:
            return dict(rows[0])
        return {"file_count": 0, "total_size": 0, "total_duration": 0}

    # ------------------------------------------------------------------
    # Year distribution
    # ------------------------------------------------------------------

    def get_year_distribution(self, library_id: str | None = None) -> list[dict[str, Any]]:
        """Return file counts grouped by year.

        Args:
            library_id: Optional library ``_id`` to scope the query.

        Returns:
            List of ``{"year": ..., "count": ...}`` dicts sorted by year
            descending. Years are extracted from ``doc.year`` on each file
            document.
        """
        from nomarr.persistence.aql import primitives

        bind_vars: dict[str, Any] = {
            "@file_collection": self.FILE_COLLECTION,
        }
        filters = ""
        if library_id is not None:
            filters = "FILTER doc.library_id == @library_id"
            bind_vars["library_id"] = library_id

        return primitives.execute(
            self._db,
            f"""
            FOR doc IN @@file_collection
                {filters}
                FILTER doc.year != null
                COLLECT year = doc.year
                    AGGREGATE count = COUNT(doc)
                SORT year DESC
                RETURN {{ year: year, count: count }}
            """,
            bind_vars,
        )

    # ------------------------------------------------------------------
    # Genre distribution
    # ------------------------------------------------------------------

    def get_genre_distribution(
        self,
        library_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return file counts grouped by genre tag value.

        Args:
            library_id: Optional library ``_id`` to scope the query.
            limit: Maximum number of genre entries to return.

        Returns:
            List of ``{"genre": ..., "count": ...}`` dicts sorted by count
            descending.
        """
        from nomarr.persistence.aql import primitives

        bind_vars: dict[str, Any] = {
            "@tag_collection": self.COLLECTION,
            "@edge_collection": self.EDGE_COLLECTION,
        }
        filters = ""
        if library_id is not None:
            # Scope via file → library edges: only count edges where the
            # file belongs to the requested library.
            bind_vars["@file_collection"] = self.FILE_COLLECTION
            bind_vars["library_id_filter"] = library_id
            filters = """
                FILTER file.library_id == @library_id_filter
            """

        query_lines = [
            "FOR tag IN @@tag_collection",
            '    FILTER tag.name == "genre"',
        ]
        if filters:
            query_lines.extend(
                [
                    "    FOR edge IN @@edge_collection",
                    "        FILTER edge._to == tag._id",
                    "        LET file = DOCUMENT(edge._from)",
                    "        FILTER file != null",
                ]
            )
            query_lines.append(filters.strip())
            query_lines.append("        COLLECT genre = tag.value AGGREGATE count = COUNT(file)")
        else:
            query_lines.extend(
                [
                    "    LET count = LENGTH(",
                    "        FOR edge IN @@edge_collection",
                    "            FILTER edge._to == tag._id",
                    "            LIMIT 1",
                    "            RETURN 1",
                    "    )",
                    "    FILTER count > 0",
                    "    COLLECT genre = tag.value AGGREGATE count = SUM(count)",
                ]
            )

        query_lines.extend(
            [
                "    SORT count DESC",
            ]
        )

        from nomarr.persistence.aql.primitives import normalize_limit

        normalized_limit = normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit_genre")
            bind_vars["limit_genre"] = normalized_limit

        query_lines.append("    RETURN { genre: genre, count: count }")

        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    # ------------------------------------------------------------------
    # Top mood pairs
    # ------------------------------------------------------------------

    def get_top_mood_pairs(
        self,
        library_id: str | None = None,
        mood_tier: str = "strict",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return the most common co-occurring mood pairs for one tier.

        Args:
            library_id: Optional library ``_id`` to scope the query.
            mood_tier: ``"strict"``, ``"regular"``, or ``"loose"``.
            limit: Maximum number of pairs to return (default 10).

        Returns:
            A list of ``{"mood1": ..., "mood2": ..., "count": ...}`` dicts
            sorted by descending count.
        """
        tier_hierarchy: dict[str, list[str]] = {
            "strict": ["nom:mood-strict"],
            "regular": ["nom:mood-strict", "nom:mood-regular"],
            "loose": ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"],
        }
        names = tier_hierarchy.get(mood_tier, ["nom:mood-strict"])

        from collections import Counter

        from nomarr.persistence.aql import primitives

        # Fetch (file_id, tag_value) pairs for all requested mood names
        tag_value_rows: list[tuple[str, str]] = []
        file_filters: dict[str, Any] = {}
        if library_id is not None:
            file_filters["library_id"] = library_id

        for name in names:
            bind_vars: dict[str, Any] = {
                "@edge_collection": self.EDGE_COLLECTION,
                "@tag_collection": self.COLLECTION,
                "tag_name": name,
            }
            query_lines = [
                "FOR tag IN @@tag_collection",
                "    FILTER tag.name == @tag_name",
                "    FOR edge IN @@edge_collection",
                "        FILTER edge._to == tag._id",
            ]
            if file_filters:
                bind_vars["@file_collection"] = self.FILE_COLLECTION
                query_lines.extend(
                    [
                        "        LET file = DOCUMENT(edge._from)",
                        "        FILTER file != null AND file.library_id == @library_id",
                    ]
                )
                if "library_id" not in bind_vars:
                    bind_vars["library_id"] = library_id
            query_lines.append("        RETURN { file_id: edge._from, value: tag.value }")

            for row in primitives.execute(self._db, "\n".join(query_lines), bind_vars):
                fid = row.get("file_id")
                val = row.get("value")
                if fid is not None and val is not None:
                    tag_value_rows.append((str(fid), str(val)))

        # Build mood-per-song map
        moods_by_song: dict[str, set[str]] = {}
        for fid, mood_value in tag_value_rows:
            if not mood_value:
                continue
            moods_by_song.setdefault(fid, set()).add(mood_value)

        # Compute pair co-occurrences
        pair_counts: Counter[tuple[str, str]] = Counter()
        for moods in moods_by_song.values():
            ordered = sorted(moods)
            if len(ordered) < 2:
                continue
            for i, m1 in enumerate(ordered[:-1]):
                for m2 in ordered[i + 1 :]:
                    pair_counts[(m1, m2)] += 1

        return [
            {"mood1": m1, "mood2": m2, "count": count}
            for (m1, m2), count in sorted(
                pair_counts.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )[:limit]
        ]
