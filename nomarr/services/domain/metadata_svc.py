"""Metadata service - entity navigation for hybrid entity graph.

Provides read-only access to entity collections and song-entity relationships.
Supports listing entities, browsing songs by entity, and traversal queries.
"""

import logging
from typing import Literal

from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Type alias for entity collection names
EntityCollection = Literal["artists", "albums", "labels", "genres", "years"]

# Mapping of entity collection to valid rel types
COLLECTION_REL_MAP: dict[EntityCollection, list[str]] = {
    "artists": ["artist", "artists"],
    "albums": ["album"],
    "labels": ["label"],
    "genres": ["genres"],
    "years": ["year"],
}


class MetadataService:
    """Service for entity navigation and song-entity relationships."""

    def __init__(self, db: Database):
        """Initialize metadata service.

        Args:
            db: Database instance
        """
        self.db = db

    def list_entities(
        self,
        collection: EntityCollection,
        limit: int = 100,
        offset: int = 0,
        search: str | None = None,
    ) -> EntityListResult:
        """List entities from a collection.

        Args:
            collection: Entity collection name
            limit: Maximum results
            offset: Skip first N results
            search: Optional substring search on display_name

        Returns:
            EntityListResult with entities, total, limit, offset
        """
        entities = self.db.entities.list_entities(collection, limit=limit, offset=offset, search=search)
        total = self.db.entities.count_entities(collection, search=search)

        entity_dicts: list[EntityDict] = [
            {
                "id": e["_id"],
                "key": e["_key"],
                "display_name": e["display_name"],
                "song_count": None,  # Not computed by default (expensive)
            }
            for e in entities
        ]

        return EntityListResult(
            entities=entity_dicts,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_entity(self, entity_id: str) -> EntityDict | None:
        """Get entity details by _id.

        Args:
            entity_id: Entity _id

        Returns:
            EntityDict or None if not found
        """
        entity = self.db.entities.get_entity(entity_id)
        if not entity:
            return None

        return EntityDict(
            id=entity["_id"],
            key=entity["_key"],
            display_name=entity["display_name"],
            song_count=None,
        )

    def list_songs_for_entity(
        self,
        entity_id: str,
        rel: str,
        limit: int = 100,
        offset: int = 0,
    ) -> SongListForEntityResult:
        """List songs connected to an entity.

        Args:
            entity_id: Entity _id
            rel: Relation type ("artist", "artists", "album", etc.)
            limit: Maximum results
            offset: Skip first N results

        Returns:
            SongListForEntityResult with song_ids, total, limit, offset
        """
        song_ids = self.db.song_tag_edges.list_songs_for_entity(entity_id, rel, limit=limit, offset=offset)
        total = self.db.song_tag_edges.count_songs_for_entity(entity_id, rel)

        return SongListForEntityResult(
            song_ids=song_ids,
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_artists_for_album(self, album_id: str, limit: int = 100) -> list[EntityDict]:
        """List artists for an album via traversal (album→songs→artists).

        Traverses: album -[rel:album]-> songs -[rel:artist]-> artists
        Deduplicates and sorts by display_name.

        Args:
            album_id: Album entity _id
            limit: Maximum artists to return

        Returns:
            List of EntityDict (artists)
        """
        # Get all songs for this album
        song_list = self.db.song_tag_edges.list_songs_for_entity(album_id, "album", limit=10000)

        # For each song, get primary artist
        artist_ids_seen = set()
        artists: list[EntityDict] = []

        for song_id in song_list:
            artist_entities = self.db.song_tag_edges.list_entities_for_song(song_id, "artist")
            for artist_entity in artist_entities:
                if artist_entity["_id"] not in artist_ids_seen:
                    artist_ids_seen.add(artist_entity["_id"])
                    artists.append(
                        EntityDict(
                            id=artist_entity["_id"],
                            key=artist_entity["_key"],
                            display_name=artist_entity["display_name"],
                            song_count=None,
                        )
                    )

        # Sort by display_name and limit
        artists.sort(key=lambda a: a["display_name"])
        return artists[:limit]

    def get_entity_counts(self) -> dict[str, int]:
        """Get total counts for all entity collections.

        Returns:
            Dict mapping collection name to count
        """
        return {
            "artists": self.db.entities.count_entities("artists"),
            "albums": self.db.entities.count_entities("albums"),
            "labels": self.db.entities.count_entities("labels"),
            "genres": self.db.entities.count_entities("genres"),
            "years": self.db.entities.count_entities("years"),
        }
