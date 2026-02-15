"""Mood-specific operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class TagMoodMixin:
    """Mood-specific operations for tags."""

    db: Any
    collection: Any

    def get_library_stats(self, library_id: str | None = None) -> dict[str, Any]:
        """Forward declaration for cross-mixin call."""
        raise NotImplementedError("get_library_stats must be provided by TagStatsMixin")

    def get_mood_and_tier_tags_for_correlation(self) -> dict[str, Any]:
        """Get mood and tier tag data for correlation analysis.

        Returns:
            Dict with keys: mood_tag_rows (list of tuples), tier_tag_keys (list), tier_tag_rows (dict)

        """
        # Get mood tags (nom:mood-strict, nom:mood-regular, nom:mood-loose)
        mood_tag_rels = ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]
        mood_tag_rows: list[tuple[str, Any]] = []

        for rel in mood_tag_rels:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN [edge._from, tag.value]
            """
            cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel})))
            mood_tag_rows.extend([tuple(row) for row in cursor])

        # Get all *_tier tag rels (nomarr only)
        query = """
        FOR tag IN tags
            FILTER STARTS_WITH(tag.rel, "nom:") AND LIKE(tag.rel, "%_tier")
            COLLECT tier_rel = tag.rel
            RETURN tier_rel
        """
        cursor = cast("Cursor", self.db.aql.execute(query))
        tier_tag_keys = list(cursor)

        # Get tier tag data for each rel
        tier_tag_rows: dict[str, list[tuple[str, Any]]] = {}
        for tier_rel in tier_tag_keys:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @tier_rel
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN [edge._from, tag.value]
            """
            cursor = cast(
                "Cursor",
                self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tier_rel": tier_rel})),
            )
            tier_tag_rows[tier_rel] = [tuple(row) for row in cursor]

        return {"mood_tag_rows": mood_tag_rows, "tier_tag_keys": tier_tag_keys, "tier_tag_rows": tier_tag_rows}

    def get_mood_distribution_data(
        self,
        library_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Get mood tag distribution for analytics.

        Args:
            library_id: Optional library _id to filter by.

        Returns:
            List of (mood_type, tag_value) tuples

        """
        mood_rows: list[tuple[str, str]] = []
        for mood_type in ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]:
            library_filter = ""
            bind_vars: dict[str, Any] = {"mood_type": mood_type}

            if library_id:
                library_filter = """
                    LET file = DOCUMENT(edge._from)
                    FILTER file != null AND file.library_id == @library_id
                """
                bind_vars["library_id"] = library_id

            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @mood_type
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN tag.value
            """
            cursor = cast(
                "Cursor",
                self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            mood_rows.extend((mood_type, str(tag_value)) for tag_value in cursor)

        return mood_rows

    def get_mood_coverage(self, library_id: str | None = None) -> dict[str, Any]:
        """Get percentage of files tagged per mood tier for Mood Analysis.

        Args:
            library_id: Optional library _id to filter by.

        Returns:
            Dict with: total_files, tiers (dict of tier_name -> {tagged, percentage})

        """
        # First get total file count
        stats = self.get_library_stats(library_id)
        total_files = stats["file_count"]

        if total_files == 0:
            return {
                "total_files": 0,
                "tiers": {
                    "strict": {"tagged": 0, "percentage": 0.0},
                    "regular": {"tagged": 0, "percentage": 0.0},
                    "loose": {"tagged": 0, "percentage": 0.0},
                },
            }

        tier_map = {
            "strict": "nom:mood-strict",
            "regular": "nom:mood-regular",
            "loose": "nom:mood-loose",
        }

        tiers: dict[str, dict[str, Any]] = {}

        for tier_name, rel in tier_map.items():
            library_filter = ""
            bind_vars: dict[str, Any] = {"rel": rel}

            if library_id:
                library_filter = "FILTER file.library_id == @library_id"
                bind_vars["library_id"] = library_id

            query = f"""
            LET tagged_files = (
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        RETURN DISTINCT edge._from
            )
            LET filtered = (
                FOR file_id IN tagged_files
                    LET file = DOCUMENT(file_id)
                    FILTER file != null
                    {library_filter}
                    RETURN 1
            )
            RETURN LENGTH(filtered)
            """
            cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
            tagged_count = next(cursor, 0)

            tiers[tier_name] = {
                "tagged": tagged_count,
                "percentage": round((tagged_count / total_files) * 100, 1) if total_files > 0 else 0.0,
            }

        return {
            "total_files": total_files,
            "tiers": tiers,
        }

    def get_mood_balance(self, library_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Get mood value distribution across tiers for Mood Analysis.

        Args:
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping tier_name -> list of {mood: str, count: int}.

        """
        tier_map = {
            "strict": "nom:mood-strict",
            "regular": "nom:mood-regular",
            "loose": "nom:mood-loose",
        }

        result: dict[str, list[dict[str, Any]]] = {}

        for tier_name, rel in tier_map.items():
            library_filter = ""
            bind_vars: dict[str, Any] = {"rel": rel}

            if library_id:
                library_filter = """
                    LET file = DOCUMENT(edge._from)
                    FILTER file != null AND file.library_id == @library_id
                """
                bind_vars["library_id"] = library_id

            # Query to get all (song_id, mood_value) pairs
            # This handles both single values and tuple representations
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN {{
                        song_id: edge._from,
                        mood: tag.value
                    }}
            """
            cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))

            # Collect and split multi-value tuples
            mood_counts: dict[str, int] = {}
            for row in cursor:
                mood_value = str(row["mood"])

                # Check if the mood value is a tuple representation
                # E.g., "('party-like', 'relaxed', 'sombre')" or "('happy',)"
                if mood_value.startswith("(") and mood_value.endswith(")"):
                    # Parse tuple string: remove parens, split by comma, strip quotes and whitespace
                    inner = mood_value[1:-1]  # Remove outer parens
                    if inner:  # Non-empty tuple
                        parts = inner.split(",")
                        for part in parts:
                            # Strip whitespace and quotes (both single and double)
                            cleaned = part.strip().strip("'\"")
                            if cleaned:  # Skip empty strings
                                mood_counts[cleaned] = mood_counts.get(cleaned, 0) + 1
                else:
                    # Single value - count it directly
                    mood_counts[mood_value] = mood_counts.get(mood_value, 0) + 1

            # Convert to list of dicts and sort by count descending
            result[tier_name] = [
                {"mood": mood, "count": count}
                for mood, count in sorted(mood_counts.items(), key=lambda x: x[1], reverse=True)
            ]

        return result

    def get_top_mood_pairs(
        self,
        library_id: str | None = None,
        limit: int = 10,
        mood_tier: str = "strict",
    ) -> list[dict[str, Any]]:
        """Get top co-occurring mood pairs for Mood Analysis.

        Finds the most common pairs of mood values that appear on the same songs.
        Tiers are cumulative: "regular" includes strict+regular, "loose" includes all.

        Args:
            library_id: Optional library _id to filter by.
            limit: Max pairs to return.
            mood_tier: Mood tier to query ("strict", "regular", or "loose").

        Returns:
            List of {mood1: str, mood2: str, count: int} sorted by count DESC.

        """
        # Tiers are cumulative: higher tiers include all stricter tiers
        tier_hierarchy: dict[str, list[str]] = {
            "strict": ["nom:mood-strict"],
            "regular": ["nom:mood-strict", "nom:mood-regular"],
            "loose": ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"],
        }
        rels = tier_hierarchy.get(mood_tier, ["nom:mood-strict"])
        library_filter = ""
        bind_vars: dict[str, Any] = {"limit": limit, "rels": rels}

        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge1._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars["library_id"] = library_id

        query = f"""
        FOR tag1 IN tags
            FILTER tag1.rel IN @rels
            FOR edge1 IN song_tag_edges
                FILTER edge1._to == tag1._id
                {library_filter}
                FOR edge2 IN song_tag_edges
                    FILTER edge2._from == edge1._from AND edge2._to != edge1._to
                    FOR tag2 IN tags
                        FILTER tag2._id == edge2._to AND tag2.rel IN @rels
                        FILTER tag1.value < tag2.value  // Avoid duplicates (A,B) and (B,A)
                        COLLECT mood1 = tag1.value, mood2 = tag2.value WITH COUNT INTO pair_count
                        SORT pair_count DESC
                        LIMIT @limit
                        RETURN {{
                            mood1: mood1,
                            mood2: mood2,
                            count: pair_count
                        }}
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def count_songs_for_tag(self, tag_id: str) -> int:
        """Count songs with this tag.

        Args:
            tag_id: Tag _id

        Returns:
            Count of songs

        """
        query = """
        RETURN LENGTH(
            FOR edge IN song_tag_edges
                FILTER edge._to == @tag_id
                RETURN 1
        )
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id})))
        result = list(cursor)
        return result[0] if result else 0
