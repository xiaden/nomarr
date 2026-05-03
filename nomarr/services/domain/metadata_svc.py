"""Metadata service - tag-based entity navigation.

Provides read-only access to tag collections and song-tag relationships.
Uses the unified tags schema where entities are just tags with specific name values.

TAG_UNIFICATION_REFACTOR: Entities are now tags. Route collection values map to name values:
    - "artist" → name="artist"
    - "album" → name="album"
    - "label" → name="label"
    - "genre" → name="genre"
    - "year" → name="year"
"""

import logging
from typing import Literal

from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags, get_orphaned_tag_count
from nomarr.components.tagging.tag_query_comp import (
    count_tags_by_name,
    get_song_tags,
    get_tag,
    list_songs_for_tag,
    list_tags_by_name,
)
from nomarr.components.tagging.tag_write_comp import find_or_create_tag
from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

# Type alias for entity collection names (for API compatibility)
EntityCollection = Literal["artist", "album", "label", "genre", "year"]

# Mapping of collection name to name value(s) for queries
COLLECTION_REL_MAP: dict[EntityCollection, str] = {
    "artist": "artist",
    "album": "album",
    "label": "label",
    "genre": "genre",
    "year": "year",
}


class MetadataService:
    """Service for tag-based entity navigation and song-tag relationships."""

    def __init__(self, db: Database) -> None:
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
        """List entities (tags) from a collection.

        Args:
            collection: Entity collection name (maps to name)
            limit: Maximum results
            offset: Skip first N results
            search: Optional substring search on value

        Returns:
            EntityListResult with entities, total, limit, offset

        """
        name = COLLECTION_REL_MAP[collection]
        tags = list_tags_by_name(self.db, name, limit=limit, offset=offset, search=search)
        total = count_tags_by_name(self.db, name, search=search)

        entity_dicts: list[EntityDict] = [
            {
                "_id": t["_id"],
                "_key": t["_key"],
                "display_name": str(t["value"]),  # value is the display name
                "song_count": t.get("song_count"),
            }
            for t in tags
        ]

        return EntityListResult(
            entities=entity_dicts,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_entity(self, entity_id: str) -> EntityDict | None:
        """Get entity (tag) details by _id.

        Args:
            entity_id: Tag _id (e.g., "tags/12345")

        Returns:
            EntityDict or None if not found

        """
        tag = get_tag(self.db, entity_id)
        if not tag:
            return None

        # Get song count for this tag
        song_count = self.db.song_has_tags._to.count(entity_id)

        return EntityDict(
            _id=tag["_id"],
            _key=tag["_key"],
            display_name=str(tag["value"]),
            song_count=song_count,
        )

    def list_songs_for_entity(
        self,
        entity_id: str,
        name: str,
        limit: int = 100,
        offset: int = 0,
    ) -> SongListForEntityResult:
        """List songs connected to an entity (tag).

        Args:
            entity_id: Tag _id
            name: Ignored (kept for API compatibility, tag knows its name)
            limit: Maximum results
            offset: Skip first N results

        Returns:
            SongListForEntityResult with song_ids, total, limit, offset

        """
        song_ids = list_songs_for_tag(self.db, entity_id, limit=limit, offset=offset)
        total = self.db.song_has_tags._to.count(entity_id)

        return SongListForEntityResult(
            song_ids=song_ids,
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_artists_for_album(self, album_id: str, limit: int = 100) -> list[EntityDict]:
        """List artists for an album via traversal (album→songs→artists).

        Traverses: album tag → songs → artist tags
        Deduplicates and sorts by value.

        Args:
            album_id: Album tag _id
            limit: Maximum artists to return

        Returns:
            List of EntityDict (artists)

        """
        # Get all songs for this album
        song_ids = list_songs_for_tag(self.db, album_id, limit=10000)

        # For each song, get primary artist tags
        artist_ids_seen: set[str] = set()
        artists: list[EntityDict] = []

        for song_id in song_ids:
            artist_tags = get_song_tags(self.db, song_id, name="artist")
            for artist_tag in artist_tags:
                # Get the first value from the tag (always a list now)
                for value in artist_tag.value:
                    tag_id = find_or_create_tag(self.db, "artist", value)
                    if tag_id not in artist_ids_seen:
                        artist_ids_seen.add(tag_id)
                        tag = get_tag(self.db, tag_id)
                        if tag:
                            artists.append(
                                EntityDict(
                                    _id=tag["_id"],
                                    _key=tag["_key"],
                                    display_name=str(tag["value"]),
                                    song_count=None,
                                ),
                            )

        # Sort by display_name and limit
        artists.sort(key=lambda a: a["display_name"])
        return artists[:limit]

    def list_albums_for_artist(self, artist_id: str, limit: int = 100) -> list[EntityDict]:
        """List albums for an artist via traversal (artist→songs→albums).

        Traverses: artist tag → songs → album tags
        Deduplicates and sorts by value.

        Args:
            artist_id: Artist tag _id
            limit: Maximum albums to return

        Returns:
            List of EntityDict (albums)

        """
        # Get all songs for this artist
        song_ids = list_songs_for_tag(self.db, artist_id, limit=10000)

        # For each song, get album tags
        album_ids_seen: set[str] = set()
        albums: list[EntityDict] = []

        for song_id in song_ids:
            album_tags = get_song_tags(self.db, song_id, name="album")
            for album_tag in album_tags:
                # Get the first value from the tag (always a list now)
                for value in album_tag.value:
                    tag_id = find_or_create_tag(self.db, "album", value)
                    if tag_id not in album_ids_seen:
                        album_ids_seen.add(tag_id)
                        tag = get_tag(self.db, tag_id)
                        if tag:
                            # Count songs in this album that are also by this artist
                            album_song_count = sum(
                                1
                                for s in song_ids
                                if any(value in t.value for t in get_song_tags(self.db, s, name="album"))
                            )
                            albums.append(
                                EntityDict(
                                    _id=tag["_id"],
                                    _key=tag["_key"],
                                    display_name=str(tag["value"]),
                                    song_count=album_song_count,
                                ),
                            )

        # Sort by display_name and limit
        albums.sort(key=lambda a: a["display_name"])
        return albums[:limit]

    def get_entity_counts(self) -> dict[str, int]:
        """Get total counts for all entity types (tag names).

        Returns:
            Dict mapping collection name to count

        """
        return {
            "artists": count_tags_by_name(self.db, "artist"),
            "albums": count_tags_by_name(self.db, "album"),
            "labels": count_tags_by_name(self.db, "label"),
            "genres": count_tags_by_name(self.db, "genre"),
            "years": count_tags_by_name(self.db, "year"),
        }

    def cleanup_orphaned_entities(self, dry_run: bool = False) -> dict[str, int | dict[str, int]]:
        """Clean up orphaned tags (tags with no edges).

        Args:
            dry_run: If True, count orphaned tags but don't delete them

        Returns:
            Dict with orphaned_count and deleted_count

        """
        if dry_run:
            orphan_count = get_orphaned_tag_count(self.db)
            return {
                "orphaned_count": orphan_count,
                "deleted_count": 0,
            }
        deleted_count = cleanup_orphaned_tags(self.db)
        return {
            "orphaned_count": deleted_count,  # Was orphaned, now deleted
            "deleted_count": deleted_count,
        }
