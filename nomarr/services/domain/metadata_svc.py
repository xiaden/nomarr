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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from nomarr.components.library.library_song_query_comp import locators_for_carriers
from nomarr.components.library.song_query_types import HydratedSong
from nomarr.components.tagging.tag_cleanup_comp import cleanup_orphaned_tags, count_orphaned_tags
from nomarr.components.tagging.tag_query_comp import count_tags_by_name, list_tags_by_name
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dto.metadata_dto import EntityDict, EntityListResult, SongListForEntityResult
from nomarr.helpers.song_locator_codec import encode_song_locator

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song
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

    def _project_song_locators(self, songs: Sequence[Song]) -> list[SongIdentity | None]:
        """Project bare semantic songs through the public carrier→locator gate.

        ``find_songs_with_tag`` returns bare ``Song`` values; the public
        projection accepts only typed carriers, so each song is wrapped in a
        metadata-only ``HydratedSong`` carrier. Order is preserved and
        unresolved songs map to ``None``. No generated integer identity, raw
        row, or private projection helper is used.
        """
        if not songs:
            return []
        return locators_for_carriers(self.db, [HydratedSong(song=song, metadata={}) for song in songs])

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
                "id": t["id"],
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

    def get_entity(self, collection: EntityCollection, entity_id: str) -> EntityDict | None:
        """Get an entity by collection and its natural tag value."""
        identity = TagRef(name=COLLECTION_REL_MAP[collection], value=entity_id)
        resolved_identity = self.db.library.get_tag(identity)
        if resolved_identity is None:
            return None
        display_name = str(resolved_identity.value)
        song_count = len(self.db.library.find_songs_with_tag(resolved_identity, limit=None))
        return EntityDict(id=display_name, display_name=display_name, song_count=song_count)

    def list_songs_for_entity(
        self,
        collection: EntityCollection,
        entity_id: str,
        name: str,  # noqa: ARG002 (intentionally unused; kept for API compatibility)
        limit: int = 100,
        offset: int = 0,
    ) -> SongListForEntityResult:
        """List songs connected to an entity (tag).

        Args:
            collection: Entity collection containing the tag
            entity_id: Natural tag value
            name: Ignored (kept for API compatibility)
            limit: Maximum results
            offset: Skip first N results

        Returns:
            SongListForEntityResult whose ``song_ids`` are opaque ``nom1``
            SongLocator tokens. Generated integer song ids never cross the
            service boundary.

        """
        identity = TagRef(name=COLLECTION_REL_MAP[collection], value=entity_id)
        songs = self.db.library.find_songs_with_tag(identity, limit=limit, offset=offset)
        total = len(self.db.library.find_songs_with_tag(identity, limit=None))
        locators = self._project_song_locators(songs)

        return SongListForEntityResult(
            song_ids=[encode_song_locator(locator) for locator in locators if locator is not None],
            total=total,
            limit=limit,
            offset=offset,
        )

    def list_artists_for_album(self, album_id: str, limit: int = 100) -> list[EntityDict]:
        """List artists for an album via traversal (album→songs→artists).

        Traverses: album tag → songs → artist tags
        Deduplicates and sorts by value.

        Args:
            album_id: Album natural tag value
            limit: Maximum artists to return

        Returns:
            List of EntityDict (artists)

        """
        # Get all songs for this album by its natural tag identity, then read
        # each song's tags through its semantic locator (never a generated id).
        songs = self.db.library.find_songs_with_tag(TagRef(name="album", value=album_id), limit=10000)
        locators = self._project_song_locators(songs)

        # Entity identity is the natural tag value (no tag PK exists); dedupe on
        # the value itself.
        artist_ids_seen: set[str] = set()
        artists: list[EntityDict] = []

        for locator in locators:
            if locator is None:
                continue
            for assignment in self.db.library.list_tags_for_song(locator):
                if assignment.name != "artist":
                    continue
                value_str = str(assignment.value)
                if value_str in artist_ids_seen:
                    continue
                artist_ids_seen.add(value_str)
                artists.append(
                    EntityDict(
                        id=value_str,
                        display_name=value_str,
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
            artist_id: Artist natural tag value
            limit: Maximum albums to return

        Returns:
            List of EntityDict (albums)

        """
        # Get all songs for this artist by its natural tag identity, then read
        # each song's tags through its semantic locator (never a generated id).
        songs = self.db.library.find_songs_with_tag(TagRef(name="artist", value=artist_id), limit=10000)
        locators = self._project_song_locators(songs)

        # Entity identity is the natural tag value (no tag PK exists); dedupe on
        # the value itself.
        album_ids_seen: set[str] = set()
        albums: list[EntityDict] = []

        for locator in locators:
            if locator is None:
                continue
            for assignment in self.db.library.list_tags_for_song(locator):
                if assignment.name != "album":
                    continue
                value_str = str(assignment.value)
                if value_str in album_ids_seen:
                    continue
                album_ids_seen.add(value_str)
                albums.append(
                    EntityDict(
                        id=value_str,
                        display_name=value_str,
                        song_count=None,
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
            dry_run: If True, count orphaned tags but don't delete them (preview)

        Returns:
            Dict with orphaned_count and deleted_count (deleted_count=0 if dry_run)

        """
        if dry_run:
            return {
                "orphaned_count": count_orphaned_tags(self.db),
                "deleted_count": 0,
            }
        result = cleanup_orphaned_tags(self.db)
        return {
            "orphaned_count": result.orphaned,
            "deleted_count": result.deleted,
        }
