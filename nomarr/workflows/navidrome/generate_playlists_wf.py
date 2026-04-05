"""Generate personal playlists for a Navidrome user from taste profile.

Produces multiple playlist types (Familiar, Discovery, Hidden Gems,
Universal) via vector ANN search on cold collections.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.navidrome.playlist_builder_comp import (
    build_discovery_playlist,
    build_familiar_playlist,
    build_genre_playlists,
    build_hidden_gems_playlist,
    build_universal_playlist,
)
from nomarr.components.navidrome.taste_profile_comp import compute_taste_profile
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
    TrackPlayData,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_BUILDERS = {
    "familiar": build_familiar_playlist,
    "discovery": build_discovery_playlist,
    "hidden_gems": build_hidden_gems_playlist,
    "universal": build_universal_playlist,
    "genre": build_genre_playlists,
}


def generate_playlists(
    db: Database,
    *,
    user_id: str,
    backbone_id: str,
    library_key: str,
    enabled_types: list[str],
    half_life_days: float,
    top_n: int,
    max_songs: int,
    min_play_count: int,
    min_songs: int,
    max_genre_playlists: int = 5,
) -> list[NavidromePersonalPlaylistEntry]:
    """Generate personal playlists for *user_id*.

    Pipeline:
        1. Compute taste profile (centroid) from play history.
        2. Fetch user's played tracks, filter by ``min_play_count``.
        3. Build ``NavidromePersonalPlaylistContext``.
        4. Dispatch each enabled playlist type to its component builder.
        5. Filter out playlists below ``min_songs``.

    Args:
        db: Database instance.
        user_id: Navidrome user identifier.
        backbone_id: Vector backbone identifier.
        library_key: ArangoDB ``_key`` of the library document.
        enabled_types: Which playlist types to generate.
        half_life_days: Recency half-life for taste profile.
        top_n: Max tracks to consider for taste profile.
        max_songs: Maximum tracks per playlist.
        min_play_count: Minimum plays for a track to count.
        min_songs: Minimum tracks for a playlist to be kept.
        max_genre_playlists: Maximum genre-specific playlists to generate (hard cap: 25).

    Returns:
        List of generated playlists with ``library_files/_id`` track lists.

    """
    # Step 1: Compute taste profile
    profile = compute_taste_profile(
        db=db,
        user_id=user_id,
        backbone_id=backbone_id,
        library_key=library_key,
        half_life_days=half_life_days,
        top_n=top_n,
    )
    if profile is None:
        logger.warning(
            "No taste profile for playlist generation — returning empty",
            extra={
                "user_id": user_id,
                "backbone_id": backbone_id,
                "library_key": library_key,
            },
        )
        return []

    # Step 2: Get user's played tracks and filter by min_play_count
    plays = db.navidrome_playcounts.get_top_plays(user_id, top_n)
    played_tracks: list[TrackPlayData] = [
        p for p in plays if p["file_id"] is not None and p["playcount"] >= min_play_count
    ]
    played_file_ids: list[str] = [p["file_id"] for p in played_tracks if p["file_id"] is not None]

    # Step 3: Build context DTO
    ctx = NavidromePersonalPlaylistContext(
        backbone_id=backbone_id,
        library_key=library_key,
        centroid=profile["centroid"],
        max_songs=max_songs,
        played_file_ids=played_file_ids,
        played_tracks=played_tracks,
        max_genre_playlists=max_genre_playlists,
        half_life_days=half_life_days,
    )

    # Step 4: Dispatch enabled types to component builders
    playlists: list[NavidromePersonalPlaylistEntry] = []

    for playlist_type in enabled_types:
        builder = _BUILDERS.get(playlist_type)
        if builder is None:
            logger.warning(
                "Unknown playlist type '%s', skipping",
                playlist_type,
                extra={
                    "user_id": user_id,
                    "backbone_id": backbone_id,
                    "library_key": library_key,
                    "playlist_type": playlist_type,
                },
            )
            continue
        playlists.extend(builder(db, ctx))

    # Step 5: Filter out playlists below min_songs
    playlists_before_filter = len(playlists)
    playlists = [p for p in playlists if len(p["file_ids"]) >= min_songs]

    if playlists_before_filter > 0 and not playlists:
        logger.warning(
            "All generated playlists were filtered out by min_songs",
            extra={
                "user_id": user_id,
                "backbone_id": backbone_id,
                "library_key": library_key,
                "playlists_before_filter": playlists_before_filter,
                "min_songs": min_songs,
            },
        )

    logger.info(
        "generate_playlists: user=%s, types=%s, produced=%d playlists",
        user_id,
        enabled_types,
        len(playlists),
    )
    return playlists
