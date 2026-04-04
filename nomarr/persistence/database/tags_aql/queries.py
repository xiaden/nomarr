"""Query operations for tags."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.tags_dto import Tags, TagValue

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class TagQueriesMixin:
    """Query operations for tags."""

    db: Any
    collection: Any

    def get_tag(self, tag_id: str) -> dict[str, Any] | None:
        """Get tag by _id. Returns {_id, _key, rel, value} or None."""
        query = """
        RETURN DOCUMENT(@tag_id)
        """
        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"tag_id": tag_id})))
        result = list(cursor)
        return result[0] if result and result[0] else None

    def list_tags_by_rel(
        self,
        rel: str | None = None,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
        sort_by_count: bool = False,
    ) -> list[dict[str, Any]]:
        """List unique tag values, optionally filtered by rel. For browse UI.

        Args:
            rel: Tag key to filter by (e.g., "artist", "album").
                 If None, list across all rels.
            limit: Max results
            offset: Pagination offset
            search: Optional substring search on value (case-insensitive)
            sort_by_count: If True, sort by song_count DESC (most common first).
                           If False (default), sort by tag.value ASC for browse/pagination.

        Returns:
            List of {_id, _key, rel, value, song_count}

        """
        filters: list[str] = []
        bind_vars: dict[str, Any] = {"limit": limit, "offset": offset}

        if rel is not None:
            filters.append("FILTER tag.rel == @rel")
            bind_vars["rel"] = rel
        if search is not None:
            filters.append("FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))")
            bind_vars["search"] = search

        filter_block = "\n                    ".join(filters)
        if sort_by_count:
            query = f"""
            FOR tag IN tags
                {filter_block}
                LET song_count = LENGTH(
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                SORT song_count DESC
                LIMIT @offset, @limit
                RETURN {{
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }}
            """
        else:
            query = f"""
            FOR tag IN tags
                {filter_block}
                SORT tag.value
                LIMIT @offset, @limit
                LET song_count = LENGTH(
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN {{
                    _id: tag._id,
                    _key: tag._key,
                    rel: tag.rel,
                    value: tag.value,
                    song_count: song_count
                }}
            """

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return list(cursor)

    def count_tags_by_rel(self, rel: str | None = None, search: str | None = None) -> int:
        """Count unique tags, optionally filtered by rel.

        Args:
            rel: Tag key to filter by. If None, count across all rels.
            search: Optional substring search on value

        Returns:
            Count of matching tags

        """
        filters: list[str] = []
        bind_vars: dict[str, Any] = {}

        if rel is not None:
            filters.append("FILTER tag.rel == @rel")
            bind_vars["rel"] = rel
        if search is not None:
            filters.append("FILTER CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@search))")
            bind_vars["search"] = search

        filter_block = "\n                    ".join(filters)
        query = f"""
        RETURN LENGTH(
            FOR tag IN tags
                {filter_block}
                RETURN 1
        )
        """

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        result = list(cursor)
        return result[0] if result else 0

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
            FOR edge IN song_has_tags
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.rel == @rel
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars: dict[str, Any] = {"song_id": song_id, "rel": rel}
        elif nomarr_only:
            query = """
            FOR edge IN song_has_tags
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND STARTS_WITH(tag.rel, "nom:")
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}
        else:
            query = """
            FOR edge IN song_has_tags
                FILTER edge._from == @song_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null
                RETURN { rel: tag.rel, value: tag.value }
            """
            bind_vars = {"song_id": song_id}

        cursor = cast("Cursor", self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)))
        return Tags.from_db_rows(list(cursor))

    def get_nomarr_tags_bulk(self, file_ids: list[str]) -> dict[str, Tags]:
        """Get Nomarr-namespaced tags for multiple files in a single AQL query.

        Args:
            file_ids: List of library file _ids (e.g., ["library_files/abc", ...])

        Returns:
            Dict mapping file_id -> Tags (nom: prefixed only).
            Files with no tags are absent from the result.

        """
        if not file_ids:
            return {}

        query = """
        FOR edge IN song_has_tags
            FILTER edge._from IN @file_ids
            LET tag = DOCUMENT(edge._to)
            FILTER tag != null AND STARTS_WITH(tag.rel, "nom:")
            RETURN { file_id: edge._from, rel: tag.rel, value: tag.value }
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"file_ids": file_ids})),
        )
        rows_by_file: dict[str, list[dict[str, Any]]] = {}
        for row in cursor:
            fid = row["file_id"]
            rows_by_file.setdefault(fid, []).append({"rel": row["rel"], "value": row["value"]})

        return {fid: Tags.from_db_rows(rows) for fid, rows in rows_by_file.items()}

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
        FOR edge IN song_has_tags
            FILTER edge._to == @tag_id
            SORT edge._from
            LIMIT @offset, @limit
            RETURN edge._from
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                query,
                bind_vars=cast("dict[str, Any]", {"tag_id": tag_id, "limit": limit, "offset": offset}),
            ),
        )
        return list(cursor)

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
                FOR edge IN song_has_tags
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """
        elif operator == "NOTCONTAINS":
            query = """
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER !CONTAINS(LOWER(TO_STRING(tag.value)), LOWER(@value))
                FOR edge IN song_has_tags
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """
        else:
            # Build dynamic filter based on operator
            # Safe operators only - map from query syntax to AQL syntax
            safe_ops = {
                "==": "==",
                "=": "==",  # Parser uses "=" for equality
                ">=": ">=",
                "<=": "<=",
                ">": ">",
                "<": "<",
                "!=": "!=",
            }
            op = safe_ops.get(operator, "==")
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER tag.value {op} @value
                FOR edge IN song_has_tags
                    FILTER edge._to == tag._id
                    RETURN DISTINCT edge._from
            """

        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        return set(cursor)

    def get_file_ids_for_tags(
        self,
        tag_specs: list[tuple[str, str]],
        library_id: str | None = None,
    ) -> dict[tuple[str, str], set[str]]:
        """Get file IDs for tag co-occurrence analysis.

        Args:
            tag_specs: List of (rel, value) tuples. Use value="*" to match any value for the key.
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping (rel, value) -> set of file_ids

        """
        result: dict[tuple[str, str], set[str]] = {}

        library_filter = ""
        bind_vars_base: dict[str, Any] = {}
        if library_id:
            library_filter = """
                LET lib_match = (
                    FOR file IN OUTBOUND @library_id library_contains_file
                        FILTER edge._from == file._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER LENGTH(lib_match) > 0
            """
            bind_vars_base["library_id"] = library_id

        for rel, value in tag_specs:
            # Coerce string value to numeric type if possible, to match stored types.
            # Tags like year ("2021"), bpm ("120") are stored as integers by parse_tag_values.
            # ArangoDB strict-type comparison means "2021" != 2021, so we must match the stored type.
            aql_value: TagValue = value
            try:
                aql_value = int(value)
            except ValueError:
                with contextlib.suppress(ValueError):
                    aql_value = float(value)

            # Support wildcard: value="*" means match any value for this key
            if value == "*":
                bind_vars = {**bind_vars_base, "rel": rel}
                query = f"""
                FOR tag IN tags
                    FILTER tag.rel == @rel
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        {library_filter}
                        RETURN edge._from
                """
            else:
                bind_vars = {**bind_vars_base, "rel": rel, "value": aql_value}
                query = f"""
                FOR tag IN tags
                    FILTER tag.rel == @rel AND tag.value == @value
                    FOR edge IN song_has_tags
                        FILTER edge._to == tag._id
                        {library_filter}
                        RETURN edge._from
                """
            cursor = cast(
                "Cursor",
                self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            result[(rel, value)] = set(cursor)

        return result

    def get_file_ids_for_mood_tags(
        self,
        mood_values: list[str],
        mood_tier: str = "mood-strict",
        library_id: str | None = None,
    ) -> dict[str, set[str]]:
        """Get file IDs for mood tag co-occurrence.

        Each mood term is stored as a plain string tag vertex (e.g. value == "aggressive").

        Args:
            mood_values: List of individual mood terms to search for (e.g., ["aggressive", "happy"])
            mood_tier: Mood tier key suffix ("mood-strict", "mood-regular", "mood-loose")
            library_id: Optional library _id to filter by.

        Returns:
            Dict mapping mood_value -> set of file_ids that contain that mood

        """
        result: dict[str, set[str]] = {}
        rel = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier

        library_filter = ""
        bind_vars_base: dict[str, Any] = {"rel": rel}
        if library_id:
            library_filter = """
                LET lib_match = (
                    FOR file IN OUTBOUND @library_id library_contains_file
                        FILTER edge._from == file._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER LENGTH(lib_match) > 0
            """
            bind_vars_base["library_id"] = library_id

        for mood_value in mood_values:
            bind_vars = {**bind_vars_base, "plain_value": mood_value}
            query = f"""
            FOR tag IN tags
                FILTER tag.rel == @rel
                FILTER tag.value == @plain_value
                FOR edge IN song_has_tags
                    FILTER edge._to == tag._id
                    {library_filter}
                    RETURN edge._from
            """
            cursor = cast(
                "Cursor",
                self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
            )
            result[mood_value] = set(cursor)

        return result

    def get_unique_mood_values(
        self,
        mood_tier: str = "mood-strict",
        limit: int = 100,
    ) -> list[str]:
        """Return unique mood tag values for a given tier, sorted alphabetically.

        Args:
            mood_tier: Mood tier suffix ("mood-strict", "mood-regular", "mood-loose")
            limit: Maximum number of unique values to return

        Returns:
            Sorted list of unique mood values

        """
        rel = f"nom:{mood_tier}" if not mood_tier.startswith("nom:") else mood_tier
        query = """
        FOR tag IN tags
            FILTER tag.rel == @rel
            SORT tag.value ASC
            LIMIT @limit
            RETURN DISTINCT tag.value
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "limit": limit})),
        )
        return [v for v in cursor if isinstance(v, str)]

    def get_distinct_tag_values_for_files(
        self,
        file_ids: list[str],
        rel: str,
    ) -> list[str]:
        """Get distinct tag values for a set of files filtered by ``rel``.

        Traverses ``song_has_tags`` edges from each file ID to tag vertices
        where ``tag.rel == @rel``, returning distinct string values.

        Args:
            file_ids: Full document IDs (e.g. ``["library_files/abc", ...]``).
            rel: Tag relationship key (e.g. ``"artist"``, ``"genre"``).

        Returns:
            Distinct tag values (unordered).

        """
        if not file_ids:
            return []

        query = """
        FOR file_id IN @file_ids
            FOR edge IN song_has_tags
                FILTER edge._from == file_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag != null AND tag.rel == @rel
                RETURN DISTINCT tag.value
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"file_ids": file_ids, "rel": rel})),
        )
        result: list[str] = [v for v in cursor if isinstance(v, str)]
        return result

    def get_tag_values_grouped_by_file(
        self,
        file_ids: list[str],
        rel: str,
    ) -> dict[str, set[str]]:
        """Get tag values per file for a given ``rel``.

        For each file, traverses ``song_has_tags`` edges to tag vertices
        filtered by ``tag.rel == @rel`` and collects the values.

        Args:
            file_ids: Full document IDs (e.g. ``["library_files/abc", ...]``).
            rel: Tag relationship key (e.g. ``"artist"``, ``"genre"``).

        Returns:
            Mapping of file document ID to set of tag value strings.
            Files with no matching tags are absent from the result.

        """
        if not file_ids:
            return {}

        query = """
        FOR file_id IN @file_ids
            LET vals = (
                FOR edge IN song_has_tags
                    FILTER edge._from == file_id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == @rel
                    RETURN tag.value
            )
            FILTER LENGTH(vals) > 0
            RETURN { file_id: file_id, values: vals }
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"file_ids": file_ids, "rel": rel})),
        )
        result: dict[str, set[str]] = {}
        for row in cursor:
            result[row["file_id"]] = {v for v in row["values"] if isinstance(v, str)}
        return result

    def get_tag_songs_with_metadata(
        self,
        tag_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get songs linked to a tag with file metadata for drill-down UI.

        Traverses ``song_has_tags`` INBOUND from the tag vertex to find
        linked library files, then returns metadata for each.

        Args:
            tag_id: Tag ``_id`` (e.g., ``"tags/12345"``).
            limit: Max results.
            offset: Pagination offset.

        Returns:
            List of ``{file_id, title, artist, album, path}``.

        """
        query = """
        FOR file IN INBOUND @tag_id song_has_tags
            SORT file._key
            LIMIT @offset, @limit
            LET artist_vals = (
                FOR e IN OUTBOUND file._id song_has_tags
                    FILTER e.rel == "artist"
                    RETURN e.value
            )
            LET album_vals = (
                FOR e IN OUTBOUND file._id song_has_tags
                    FILTER e.rel == "album"
                    RETURN e.value
            )
            RETURN {
                file_id: file._id,
                title: file.title,
                artist: FIRST(artist_vals) || "",
                album: FIRST(album_vals) || "",
                path: file.path
            }
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                query,
                bind_vars=cast("dict[str, Any]", {"tag_id": tag_id, "limit": limit, "offset": offset}),
            ),
        )
        return list(cursor)
