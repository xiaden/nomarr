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
    top_plays: list[TrackPlayData],
    backbone_id: str,
    enabled_types: list[str],
    half_life_days: float,
    top_n: int,
    max_songs: int,
    min_play_count: int,
    min_songs: int,
    max_genre_playlists: int = 5,
    pp_max_clusters: int = 10,
) -> list[NavidromePersonalPlaylistEntry]:
    """Generate personal playlists for *user_id* from caller-provided play history.

    Pipeline:
        1. Compute taste profile (multi-cluster) from caller-provided play history.
        2. Filter provided plays by ``min_play_count``.
        3. Build ``NavidromePersonalPlaylistContext``.
        4. Dispatch each enabled playlist type to its component builder.
        5. Filter out playlists below ``min_songs``.

    Vector collections are per-backbone (no library_key needed).

    Args:
        db: Database instance.
        user_id: Navidrome user identifier.
        top_plays: Play history provided by the caller (e.g. Navidrome plugin).
            Each entry must include ``file_id``, ``playcount``, and ``last_played``.
        backbone_id: Vector backbone identifier.
        enabled_types: Which playlist types to generate.
        half_life_days: Recency half-life for taste profile.
        top_n: Max tracks to consider for taste profile.
        max_songs: Maximum tracks per playlist.
        min_play_count: Minimum plays for a track to count.
        min_songs: Minimum tracks for a playlist to be kept.
        max_genre_playlists: Maximum genre-specific playlists to generate (hard cap: 25).
        pp_max_clusters: Maximum number of genre clusters for taste profile computation.

    Returns:
        List of generated playlists with ``song/_id`` track lists.

    """
    # Step 1: Compute taste profile from caller-provided play data
    profile = compute_taste_profile(
        db=db,
        user_id=user_id,
        top_plays=top_plays,
        backbone_id=backbone_id,
        half_life_days=half_life_days,
        top_n=top_n,
        pp_max_clusters=pp_max_clusters,
    )
    if profile is None:
        logger.warning(
            "No taste profile for playlist generation — returning empty",
            extra={
                "user_id": user_id,
                "backbone_id": backbone_id,
            },
        )
        return []

    # Step 2: Use caller-provided play data (sliced to top_n) and filter by min_play_count
    plays = list(top_plays[:top_n])
    played_tracks: list[TrackPlayData] = [
        p for p in plays if p["file_id"] is not None and p["playcount"] >= min_play_count
    ]
    played_file_ids: list[int] = [p["file_id"] for p in played_tracks if p["file_id"] is not None]

    # Step 3: Build context DTO
    # TODO(S6): NavidromePersonalPlaylistContext.played_file_ids should be list[int]
    ctx = NavidromePersonalPlaylistContext(
        backbone_id=backbone_id,
        clusters=profile["clusters"],
        max_songs=max_songs,
        played_file_ids=played_file_ids,  # type: ignore[typeddict-item]
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
