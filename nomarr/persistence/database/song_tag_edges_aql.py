"""Song-tag edge operations for ArangoDB (entity→song metadata relationships).

song_tag_edges is an EDGE collection connecting entities → songs.
All operations use graph semantics (_from, _to, rel).
"""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase


class SongTagEdgeOperations:
    """Operations for song_tag_edges edge collection (entity→song associations)."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("song_tag_edges")

    def replace_song_relations(
        self,
        song_id: str,
        rel: str,
        entity_ids: list[str],
    ) -> None:
        """Replace all edges for a song and relation type.

        Deletes existing edges matching (song_id, rel), then inserts new edges.
        Inserts are deterministic (sorted entity_ids).

        Args:
            song_id: Song document _id (e.g., "library_files/12345")
            rel: Relation type ("artist", "artists", "album", "label", "genres", "year")
            entity_ids: List of entity _ids (e.g., ["artists/v1_abc...", ...])
        """
        # Delete existing edges for this song+rel
        self.db.aql.execute(
            """
            FOR edge IN song_tag_edges
                FILTER edge._to == @song_id AND edge.rel == @rel
                REMOVE edge IN song_tag_edges
            """,
            bind_vars={"song_id": song_id, "rel": rel},
        )

        # Insert new edges (deterministic order)
        sorted_entity_ids = sorted(entity_ids)
        for entity_id in sorted_entity_ids:
            self.collection.insert(
                {
                    "_from": entity_id,
                    "_to": song_id,
                    "rel": rel,
                },
                silent=True,  # Ignore duplicates
            )

    def list_songs_for_entity(
        self,
        entity_id: str,
        rel: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[str]:
        """List song _ids connected to an entity.

        Args:
            entity_id: Entity _id (e.g., "artists/v1_abc...")
            rel: Relation type to filter by
            limit: Maximum results
            offset: Skip first N results

        Returns:
            List of song _ids
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR edge IN song_tag_edges
                FILTER edge._from == @entity_id AND edge.rel == @rel
                SORT edge._to
                LIMIT @offset, @limit
                RETURN edge._to
            """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "entity_id": entity_id,
                        "rel": rel,
                        "limit": limit,
                        "offset": offset,
                    },
                ),
            ),
        )
        return list(cursor)

    def count_songs_for_entity(self, entity_id: str, rel: str) -> int:
        """Count songs connected to an entity.

        Args:
            entity_id: Entity _id
            rel: Relation type

        Returns:
            Total count
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            RETURN LENGTH(
                FOR edge IN song_tag_edges
                    FILTER edge._from == @entity_id AND edge.rel == @rel
                    RETURN 1
            )
            """,
                bind_vars={"entity_id": entity_id, "rel": rel},
            ),
        )
        result = next(cursor, 0)
        return int(result)

    def list_entities_for_song(
        self,
        song_id: str,
        rel: str,
    ) -> list[dict[str, Any]]:
        """List entity documents connected to a song.

        Args:
            song_id: Song _id (e.g., "library_files/12345")
            rel: Relation type to filter by

        Returns:
            List of entity dicts with '_id', '_key', 'display_name'
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR edge IN song_tag_edges
                FILTER edge._to == @song_id AND edge.rel == @rel
                LET entity = DOCUMENT(edge._from)
                SORT entity.display_name
                RETURN {
                    _id: entity._id,
                    _key: entity._key,
                    display_name: entity.display_name
                }
            """,
                bind_vars={"song_id": song_id, "rel": rel},
            ),
        )
        return list(cursor)

    def delete_song_edges(self, song_id: str) -> None:
        """Delete all entity edges for a song.

        Args:
            song_id: Song _id to remove edges for
        """
        self.db.aql.execute(
            """
            FOR edge IN song_tag_edges
                FILTER edge._to == @song_id
                REMOVE edge IN song_tag_edges
            """,
            bind_vars={"song_id": song_id},
        )

    def delete_entity_edges(self, entity_id: str) -> None:
        """Delete all edges for an entity (orphan cleanup).

        Args:
            entity_id: Entity _id to remove edges for
        """
        self.db.aql.execute(
            """
            FOR edge IN song_tag_edges
                FILTER edge._from == @entity_id
                REMOVE edge IN song_tag_edges
            """,
            bind_vars={"entity_id": entity_id},
        )
