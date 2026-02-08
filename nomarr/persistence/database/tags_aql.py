"""Unified tag operations for the tags collection.

This is the ONLY canonical tag persistence implementation.
All tag read/write operations go through this module.

Schema:
    tags vertex collection: { _key, rel: str, value: scalar }
    song_tag_edges edge collection: { _from: library_files/_id, _to: tags/_id }

Uniqueness:
    A tag is uniquely identified by (rel, value) pair.
    Edge uniqueness enforced by unique index on [_from, _to].

Provenance Convention:
    - Nomarr-generated tags: rel starts with "nom:" (e.g., "nom:mood-strict")
    - External/user tags: all other rel values (e.g., "artist", "album", "genre")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.tags_dto import Tags, TagValue

if TYPE_CHECKING:
    from arango.cursor import Cursor
    from arango.database import StandardDatabase

    from nomarr.persistence.arango_client import SafeDatabase

logger = logging.getLogger(__name__)

# TagValue is imported from nomarr.helpers.dto.tags_dto


class TagOperations:
    """Unified tag operations for the tags collection."""

    def __init__(self, db: StandardDatabase | SafeDatabase) -> None:
        self._db = db

    # ──────────────────────────────────────────────────────────────────────
    # Tag vertex operations
    # ──────────────────────────────────────────────────────────────────────

    def find_or_create_tag(self, rel: str, value: TagValue) -> str:
        """Find or create a tag vertex. Returns tag _id.

        Uses UPSERT on (rel, value) unique index for idempotency.

        Args:
            rel: Tag key (e.g., "artist", "album", "nom:mood-strict")
            value: Scalar value (str|int|float|bool). NOT a list. NOT JSON.

        Returns:
            Tag document _id (e.g., "tags/12345")

        """
        query = """
        UPSERT { rel: @rel, value: @value }
        INSERT { rel: @rel, value: @value }
        UPDATE {}
        IN tags
        RETURN NEW._id
        """
        cursor = cast(
            "Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        result = list(cursor)
        return str(result[0])

    def get_tag(self, tag_id: str) -> dict[str, Any] | None:
        """Get tag by _id. Returns {_id, _key, rel, value} or None."""
        query = """
        RETURN DOCUMENT(@tag_id)
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id})))
        result = list(cursor)
        return result[0] if result and result[0] else None

    def list_tags_by_rel(
        self, rel: str, limit: int = 100, offset: int = 0, search: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all unique tag values for a rel. For browse UI.

        Args:
            rel: Tag key to filter by (e.g., "artist", "album")
            limit: Max results
            offset: Pagination offset
            search: Optional substring search on value (case-insensitive)

        Returns:
            List of {_id, _key, rel, value, song_count}

        """
        if search:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))
                SORT tag.value
                LIMIT @offset, @limit
                LET song_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN {
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }
            """
            bind_vars = {"rel": rel, "search": search, "limit": limit, "offset": offset}
        else:
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                SORT tag.value
                LIMIT @offset, @limit
                LET song_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN {
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }
            """
            bind_vars = {"rel": rel, "limit": limit, "offset": offset}

        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def count_tags_by_rel(self, rel: str, search: str | None = None) -> int:
        """Count unique tags for a rel.

        Args:
            rel: Tag key to filter by
            search: Optional substring search on value

        Returns:
            Count of matching tags

        """
        if search:
            query = """
            RETURN LENGTH(
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))
                    RETURN 1
            )
            """
            bind_vars = {"rel": rel, "search": search}
        else:
            query = """
            RETURN LENGTH(
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    RETURN 1
            )
            """
            bind_vars = {"rel": rel}

        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        result = list(cursor)
        return result[0] if result else 0

    # ──────────────────────────────────────────────────────────────────────
    # Edge operations (song ↔ tag relationships)
    # ──────────────────────────────────────────────────────────────────────

    def set_song_tags(self, song_id: str, rel: str, values: list[TagValue]) -> None:
        """Replace all tags for a song+rel. Creates tag vertices as needed.

        This is a full replacement: existing edges for (song_id, rel) are deleted,
        then new edges are created for each value.

        Uses UPSERT for edges to ensure idempotency (unique index on [_from, _to]).

        Args:
            song_id: Song _id (e.g., "library_files/abc123")
            rel: Tag key (e.g., "artist", "album", "nom:mood-strict")
            values: List of scalar values. Empty list clears all tags for this rel.

        Note:
            Nomarr provenance is implicit in rel prefix ("nom:*").

        """
        # First, delete existing edges for this song+rel
        delete_query = """
        FOR edge IN song_tag_edges
            FILTER edge._from == @song_id
            LET tag = DOCUMENT(edge._to)
            FILTER tag != null AND tag.rel == @rel
            REMOVE edge IN song_tag_edges
        """
        self._db.aql.execute(delete_query, bind_vars=cast("dict[str, Any]", {"song_id": song_id, "rel": rel}))

        # Then create new edges for each value (with UPSERT for idempotency)
        if values:
            # First ensure all tag vertices exist
            tag_create_query = """
            FOR value IN @values
                UPSERT { rel: @rel, value: value }
                INSERT { rel: @rel, value: value }
                UPDATE {}
                IN tags
            """
            self._db.aql.execute(tag_create_query, bind_vars=cast("dict[str, Any]", {"rel": rel, "values": values}))

            # Then create edges from song to tags
            edge_create_query = """
            FOR value IN @values
                LET tag = FIRST(
                    FOR t IN tags
                        FILTER t.rel == @rel AND t.value == value
                        RETURN t
                )
                FILTER tag != null
                UPSERT { _from: @song_id, _to: tag._id }
                INSERT { _from: @song_id, _to: tag._id }
                UPDATE {}
                IN song_tag_edges
            """
            self._db.aql.execute(
                edge_create_query, bind_vars=cast("dict[str, Any]", {"song_id": song_id, "rel": rel, "values": values}),
            )

    def add_song_tag(self, song_id: str, rel: str, value: TagValue) -> None:
        """Add a single tag to a song (without replacing existing tags for this rel).

        Uses UPSERT for both tag and edge to ensure idempotency.

        Args:
            song_id: Song _id (e.g., "library_files/abc123")
            rel: Tag key (e.g., "nom:danceability_...")
            value: Scalar value

        """
        # First ensure tag vertex exists
        tag_query = """
        UPSERT { rel: @rel, value: @value }
        INSERT { rel: @rel, value: @value }
        UPDATE {}
        IN tags
        RETURN NEW._id
        """
        cursor = cast(
            "Cursor", self._db.aql.execute(tag_query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        tag_id = next(iter(cursor))

        # Then create edge
        edge_query = """
        UPSERT { _from: @song_id, _to: @tag_id }
        INSERT { _from: @song_id, _to: @tag_id }
        UPDATE {}
        IN song_tag_edges
        """
        self._db.aql.execute(edge_query, bind_vars=cast("dict[str, Any]", {"song_id": song_id, "tag_id": tag_id}))

    def get_song_tags(self, song_id: str, rel: str | None = None, nomarr_only: bool = False) -> Tags:
        """Get all tags for a song, optionally filtered by rel or Nomarr prefix.

        Args:
            song_id: Song _id
            rel: Optional filter by specific rel (e.g., "artist")
            nomarr_only: If True, filter by STARTS_WITH(rel, "nom:")

        Returns:
            Tags collection (use .to_dict() for dict format)

        """
        if rel:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.rel == @rel
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars: dict[str, Any] = {"song_id": song_id, "rel": rel}
        elif nomarr_only:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND STARTS_WITH(tag.rel, "nom:")
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}
        else:
            query = """
            FOR edge IN song_tag_edges
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}

        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return Tags.from_db_rows(list(cursor))

    def list_songs_for_tag(self, tag_id: str, limit: int = 100, offset: int = 0) -> list[str]:
        """List song _ids with this tag. For browse drill-down.

        Args:
            tag_id: Tag _id (e.g., "tags/12345")
            limit: Max results
            offset: Pagination offset

        Returns:
            List of song _ids

        """
        query = """
        FOR edge IN song_tag_edges
            FILTER edge._to == @tag_id
            SORT edge._from
            LIMIT @offset, @limit
            RETURN edge._from
        """
        cursor = cast(
            "Cursor",
            self._db.aql.execute(
                query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id, "limit": limit, "offset": offset}),
            ),
        )
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
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id})))
        result = list(cursor)
        return result[0] if result else 0

    def delete_song_tags(self, song_id: str) -> None:
        """Delete all tag edges for a song (on file delete).

        Args:
            song_id: Song _id

        """
        query = """
        FOR edge IN song_tag_edges
            FILTER edge._from == @song_id
            REMOVE edge IN song_tag_edges
        """
        self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"song_id": song_id}))

    def cleanup_orphaned_tags(self) -> int:
        """Delete tags with no edges. Returns count deleted.

        Use this periodically or after bulk file deletions.
        """
        query = """
        LET orphans = (
            FOR tag IN tags
                LET edge_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER edge_count == 0
                RETURN tag._key
        )
        FOR key IN orphans
            REMOVE { _key: key } IN tags
        RETURN LENGTH(orphans)
        """
        cursor = cast("Cursor", self._db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0

    def get_orphaned_tag_count(self) -> int:
        """Count tags with no edges (for reporting before cleanup)."""
        query = """
        RETURN LENGTH(
            FOR tag IN tags
                LET edge_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER edge_count == 0
                RETURN 1
        )
        """
        cursor = cast("Cursor", self._db.aql.execute(query))
        result = list(cursor)
        return result[0] if result else 0

    # ──────────────────────────────────────────────────────────────────────
    # Analytics / query helpers
    # ──────────────────────────────────────────────────────────────────────

    def get_unique_rels(self, nomarr_only: bool = False) -> list[str]:
        """Get all unique rel values in the tags collection.

        Args:
            nomarr_only: If True, only return rels starting with "nom:"

        Returns:
            List of unique rel strings

        """
        if nomarr_only:
            query = """
            FOR tag IN tags
                FILTER STARTS_WITH(tag.rel, "nom:")
                COLLECT rel = tag.rel
                RETURN rel
            """
        else:
            query = """
            FOR tag IN tags
                COLLECT rel = tag.rel
                RETURN rel
            """
        cursor = cast("Cursor", self._db.aql.execute(query))
        return list(cursor)

    def get_tag_value_counts(self, rel: str) -> dict[Any, int]:
        """Get value counts for a specific rel (for analytics).

        Args:
            rel: Tag key to analyze

        Returns:
            Dict of {value: song_count}

        """
        query = """
        FOR tag IN tags
            FILTER tag.rel == @rel
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            RETURN { value: tag.value, count: song_count }
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel})))
        return {row["value"]: row["count"] for row in cursor}

    def get_file_ids_matching_tag(self, rel: str, operator: str, value: TagValue) -> set[str]:
        """Get file IDs matching a tag condition.

        Args:
            rel: Tag key
            operator: Comparison operator ("==", ">=", "<=", ">", "<", "CONTAINS")
            value: Value to compare

        Returns:
            Set of file _ids matching the condition

        """
        if operator == "CONTAINS":
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@value))
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """
        else:
            # Build dynamic filter based on operator
            # Safe operators only
            safe_ops = {"==": "==", ">=": ">=", "<=": "<=", ">": ">", "<": "<"}
            op = safe_ops.get(operator, "==")
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER tag.value {op} @value
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """

        cursor = cast(
            "Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        return set(cursor)

    # ──────────────────────────────────────────────────────────────────────
    # Analytics service helpers
    # ──────────────────────────────────────────────────────────────────────

    def get_tag_frequencies(self, limit: int, namespace_prefix: str) -> dict[str, Any]:
        """Get tag frequency data for analytics.

        Args:
            limit: Max results per category
            namespace_prefix: Prefix to filter nomarr tags (e.g., "nom:")

        Returns:
            Dict with keys: nom_tag_rows (list of tuples), genre_rows (list of tuples)

        """
        # Count Nomarr tag rel:value combinations (rel starts with namespace_prefix)
        # Extract the key portion after the prefix for display
        query = """
        FOR tag IN tags
            FILTER STARTS_WITH(tag.rel, @prefix)
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            FILTER song_count > 0
            LET key_part = SUBSTRING(tag.rel, LENGTH(@prefix))
            COLLECT tag_key_value = CONCAT(key_part, ':', tag.value) WITH COUNT INTO tag_count
            SORT tag_count DESC
            LIMIT @limit
            RETURN [tag_key_value, tag_count]
        """
        cursor = cast(
            "Cursor",
            self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"prefix": namespace_prefix, "limit": limit})),
        )
        nom_tag_rows = [tuple(row) for row in cursor]

        # Count genre tags (rel == "genre", non-Nomarr)
        query = """
        FOR tag IN tags
            FILTER tag.rel == "genre"
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    RETURN 1
            )
            FILTER song_count > 0
            COLLECT genre = tag.value WITH COUNT INTO count
            SORT count DESC
            LIMIT @limit
            RETURN [genre, count]
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"limit": limit})))
        genre_rows = [tuple(row) for row in cursor]

        return {"nom_tag_rows": nom_tag_rows, "genre_rows": genre_rows}

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
            cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel})))
            mood_tag_rows.extend([tuple(row) for row in cursor])

        # Get all *_tier tag rels (nomarr only)
        query = """
        FOR tag IN tags
            FILTER STARTS_WITH(tag.rel, "nom:") AND LIKE(tag.rel, "%_tier")
            COLLECT tier_rel = tag.rel
            RETURN tier_rel
        """
        cursor = cast("Cursor", self._db.aql.execute(query))
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
                "Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tier_rel": tier_rel})),
            )
            tier_tag_rows[tier_rel] = [tuple(row) for row in cursor]

        return {"mood_tag_rows": mood_tag_rows, "tier_tag_keys": tier_tag_keys, "tier_tag_rows": tier_tag_rows}

    def get_mood_distribution_data(
        self, library_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Get mood tag distribution for analytics.

        Args:
            library_id: Optional library _id to filter by.

        Returns:
            List of (mood_type, tag_value) tuples

        """
        mood_rows: list[tuple[str, str]] = []
        for mood_type in ["nom:mood-strict", "nom:mood-relaxed", "nom:mood-genre"]:
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
                "Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            mood_rows.extend((mood_type, str(tag_value)) for tag_value in cursor)

        return mood_rows

    def get_file_ids_for_tags(
        self, tag_specs: list[tuple[str, str]], library_id: str | None = None,
    ) -> dict[tuple[str, str], set[str]]:
        """Get file IDs for tag co-occurrence analysis.

        Args:
            tag_specs: List of (rel, value) tuples
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping (rel, value) -> set of file_ids

        """
        result: dict[tuple[str, str], set[str]] = {}

        library_filter = ""
        bind_vars_base: dict[str, Any] = {}
        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars_base["library_id"] = library_id

        for rel, value in tag_specs:
            bind_vars = {**bind_vars_base, "rel": rel, "value": value}
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel AND tag.value == @value
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN edge._from
            """
            cursor = cast(
                "Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            result[(rel, value)] = set(cursor)

        return result


    # ──────────────────────────────────────────────────────────────────────────────
    # Collection Profile Analytics (library-filtered)
    # ──────────────────────────────────────────────────────────────────────────────

    def get_library_stats(self, library_id: str | None = None) -> dict[str, Any]:
        """Get aggregate library statistics for Collection Overview.

        Args:
            library_id: Optional library _id to filter by (e.g., "libraries/12345").
                        If None, returns stats for all libraries.

        Returns:
            Dict with keys: file_count, total_duration_ms, total_file_size_bytes,
                           avg_track_length_ms
        """
        filter_clause = "FILTER file.library_id == @library_id" if library_id else ""
        bind_vars: dict[str, Any] = {"library_id": library_id} if library_id else {}

        query = f"""
        FOR file IN library_files
            {filter_clause}
            COLLECT AGGREGATE
                file_count = COUNT(1),
                total_duration_s = SUM(file.duration_seconds),
                total_size = SUM(file.file_size)
            RETURN {{
                file_count: file_count,
                total_duration_ms: (total_duration_s || 0) * 1000,
                total_file_size_bytes: total_size || 0,
                avg_track_length_ms: file_count > 0
                    ? ((total_duration_s || 0) / file_count) * 1000
                    : 0
            }}
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        result = next(cursor, None)
        return result or {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }

    def get_year_distribution(self, library_id: str | None = None) -> list[dict[str, Any]]:
        """Get year/decade distribution for Collection Overview.

        Args:
            library_id: Optional library _id to filter by.
                        If None, returns stats for all libraries.

        Returns:
            List of {year: int, count: int} sorted by year ascending.
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
            SORT tag.value ASC
            RETURN {{
                year: tag.value,
                count: song_count
            }}
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def get_genre_distribution(
        self, library_id: str | None = None, limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get genre distribution for Collection Overview.

        Args:
            library_id: Optional library _id to filter by.
            limit: Max genres to return (sorted by count desc).

        Returns:
            List of {genre: str, count: int} sorted by count descending.
        """
        library_filter = ""
        bind_vars: dict[str, Any] = {"limit": limit}

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
            LIMIT @limit
            RETURN {{
                genre: tag.value,
                count: song_count
            }}
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def get_artist_distribution(
        self, library_id: str | None = None, limit: int = 20,
    ) -> dict[str, Any]:
        """Get artist distribution for Collection Overview.

        Args:
            library_id: Optional library _id to filter by.
            limit: Max artists to return in top list.

        Returns:
            Dict with: top_artists (list of {artist, count}), others_count (int),
                       total_artists (int)
        """
        library_filter = ""
        bind_vars: dict[str, Any] = {"limit": limit}

        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars["library_id"] = library_id

        # Get all artists with counts
        query = f"""
        FOR tag IN tags
            FILTER tag.rel == "artist"
            LET song_count = LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN 1
            )
            FILTER song_count > 0
            SORT song_count DESC
            RETURN {{
                artist: tag.value,
                count: song_count
            }}
        """
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        all_artists = list(cursor)

        total_artists = len(all_artists)
        top_artists = all_artists[:limit]
        others_count = sum(a["count"] for a in all_artists[limit:])

        return {
            "top_artists": top_artists,
            "others_count": others_count,
            "total_artists": total_artists,
        }


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
                    "relaxed": {"tagged": 0, "percentage": 0.0},
                    "genre": {"tagged": 0, "percentage": 0.0},
                },
            }

        tier_map = {
            "strict": "nom:mood-strict",
            "relaxed": "nom:mood-relaxed",
            "genre": "nom:mood-genre",
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
            cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
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
            "relaxed": "nom:mood-relaxed",
            "genre": "nom:mood-genre",
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

            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                LET song_count = LENGTH(
                    FOR edge IN song_tag_edges
                        FILTER edge._to == tag._id
                        {library_filter}
                        RETURN 1
                )
                FILTER song_count > 0
                SORT song_count DESC
                RETURN {{
                    mood: tag.value,
                    count: song_count
                }}
            """
            cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
            result[tier_name] = list(cursor)

        return result

    def get_top_mood_pairs(
        self, library_id: str | None = None, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top co-occurring mood pairs for Mood Analysis.

        Finds the most common pairs of mood values that appear on the same songs.

        Args:
            library_id: Optional library _id to filter by.
            limit: Max pairs to return.

        Returns:
            List of {mood1: str, mood2: str, count: int} sorted by count DESC.
        """
        library_filter = ""
        bind_vars: dict[str, Any] = {"limit": limit}

        if library_id:
            library_filter = """
                LET file = DOCUMENT(edge1._from)
                FILTER file != null AND file.library_id == @library_id
            """
            bind_vars["library_id"] = library_id

        query = f"""
        FOR tag1 IN tags
            FILTER STARTS_WITH(tag1.rel, "nom:mood-")
            FOR edge1 IN song_tag_edges
                FILTER edge1._to == tag1._id
                {library_filter}
                FOR edge2 IN song_tag_edges
                    FILTER edge2._from == edge1._from AND edge2._to != edge1._to
                    FOR tag2 IN tags
                        FILTER tag2._id == edge2._to AND STARTS_WITH(tag2.rel, "nom:mood-")
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
        cursor = cast("Cursor", self._db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)
