"""CRUD operations for tags."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

from nomarr.helpers.dto.tags_dto import TagValue

logger = logging.getLogger(__name__)


class TagCrudMixin:
    """CRUD operations for tags."""

    db: Any
    collection: Any

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
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        result = list(cursor)
        return str(result[0])

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
        self.db.aql.execute(delete_query, bind_vars=cast("dict[str, Any]", {"song_id": song_id, "rel": rel}))

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
            self.db.aql.execute(tag_create_query, bind_vars=cast("dict[str, Any]", {"rel": rel, "values": values}))

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
            self.db.aql.execute(
                edge_create_query,
                bind_vars=cast("dict[str, Any]", {"song_id": song_id, "rel": rel, "values": values}),
            )

    def set_song_tags_batch(
        self,
        entries: list[dict[str, Any]],
    ) -> None:
        """Replace tags for multiple (song_id, rel) pairs in 3 AQL queries.

        Each entry is ``{"song_id": str, "rel": str, "values": list[TagValue]}``.
        This is functionally equivalent to calling :meth:`set_song_tags` once
        per entry but collapses all work into 3 AQL round-trips:

        1. Delete existing edges for every (song_id, rel) pair
        2. UPSERT all tag vertices
        3. UPSERT all edges

        Args:
            entries: List of dicts with song_id, rel, values keys.
                     Empty *values* list clears tags for that (song_id, rel).

        """
        if not entries:
            return

        # Prepare serialisable entries for bind vars
        bind_entries = [{"song_id": e["song_id"], "rel": e["rel"], "values": e["values"]} for e in entries]

        # 1) Delete existing edges for all (song_id, rel) pairs
        self.db.aql.execute(
            """
            FOR entry IN @entries
                FOR edge IN song_tag_edges
                    FILTER edge._from == entry.song_id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null AND tag.rel == entry.rel
                    REMOVE edge IN song_tag_edges
            """,
            bind_vars=cast("dict[str, Any]", {"entries": bind_entries}),
        )

        # Filter to entries that have values (need vertex + edge creation)
        with_values = [e for e in bind_entries if e["values"]]
        if not with_values:
            return

        # 2) UPSERT tag vertices for all (rel, value) pairs
        self.db.aql.execute(
            """
            FOR entry IN @entries
                FOR value IN entry.values
                    UPSERT { rel: entry.rel, value: value }
                    INSERT { rel: entry.rel, value: value }
                    UPDATE {}
                    IN tags
            """,
            bind_vars=cast("dict[str, Any]", {"entries": with_values}),
        )

        # 3) Create edges from song to tags

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
            "Cursor",
            self.db.aql.execute(tag_query, bind_vars=cast("dict[str, Any]", {"rel": rel, "value": value})),
        )
        tag_id = next(iter(cursor))

        # Then create edge
        edge_query = """
        UPSERT { _from: @song_id, _to: @tag_id }
        INSERT { _from: @song_id, _to: @tag_id }
        UPDATE {}
        IN song_tag_edges
        """
        self.db.aql.execute(edge_query, bind_vars=cast("dict[str, Any]", {"song_id": song_id, "tag_id": tag_id}))

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
        self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", {"song_id": song_id}))
