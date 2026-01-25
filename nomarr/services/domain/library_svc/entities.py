"""Library entities navigation.

This module is a placeholder for entity navigation functionality.
Entity navigation (artists, albums, tracks) is currently in metadata_svc.py
and may be consolidated here in a future refactor.

See the services audit report for recommendations on merging entity
navigation functionality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryEntitiesMixin:
    """Mixin providing library entity navigation.

    This is currently a placeholder. Entity navigation functionality
    (get_artists, get_albums, get_tracks, etc.) lives in MetadataService
    and may be consolidated here in a future refactor.

    See: nomarr/services/domain/metadata_svc.py
    """

    db: Database
    cfg: LibraryServiceConfig

    # Future methods to be moved from MetadataService:
    # - get_artists()
    # - get_albums()
    # - get_tracks()
    # - get_artist_details()
    # - get_album_details()
    # - get_track_details()
