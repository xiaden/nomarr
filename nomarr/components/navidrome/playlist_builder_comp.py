"""Build personal playlist track lists from taste profiles and play history.

Each public function encapsulates the domain logic for one playlist type:
ANN search, exclusion filtering, and result assembly.  All AQL access
goes through ``db.tags.*`` persistence methods.

Every builder has the uniform signature::

    (db: Database, ctx: NavidromePersonalPlaylistContext)
        -> list[NavidromePersonalPlaylistEntry]

Builders return only ``library_files/_id`` values.  Navidrome nd_id
resolution is the interface layer's responsibility.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import sanitize_genre_name
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

#: Minimum tracks for a genre playlist to be included in the output.
_GENRE_MIN_SONGS: int = 5


# ------------------------------------------------------------------
# Public builder functions
# ------------------------------------------------------------------


def build_familiar_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Familiar playlist: ANN search biased toward played tracks.

    Uses the taste centroid for ANN search on the global cold collection,
    then *includes only* played tracks that appear in the results.  This
    keeps the playlist sonically coherent (centroid-near) while limiting
    it to music the user already knows.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Familiar playlist, or empty list
        if no played tracks appear in ANN results.

    """
    played = set(ctx["played_file_ids"])
    if not played:
        return []

    cold_ops = db.get_vectors_track_cold(ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    # Over-fetch: most results won't be in the played set
    fetch_limit = ctx["max_songs"] * 5
    raw_results = cold_ops.search_similar(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Keep only tracks the user has played, preserving ANN ranking
    file_ids = [
        r["file_id"] for r in raw_results
        if r["file_id"] in played
    ][: ctx["max_songs"]]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="familiar",
            playlist_name="Your Favorites",
            file_ids=file_ids,
        )
    ]


def build_discovery_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Discovery playlist: ANN search excluding played tracks.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Discovery playlist, or empty list
        if the cold collection is empty.

    """
    played = set(ctx["played_file_ids"])

    cold_ops = db.get_vectors_track_cold(ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 2
    raw_results = cold_ops.search_similar(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Exclude played tracks
    file_ids = [
        r["file_id"] for r in raw_results if r["file_id"] not in played
    ][: ctx["max_songs"]]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="discovery",
            playlist_name="Discover Weekly",
            file_ids=file_ids,
        )
    ]


def build_hidden_gems_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Hidden Gems playlist: ANN search excluding known-artist tracks.

    Filters out tracks by artists the user has already listened to,
    surfacing music from unfamiliar artists near the taste centroid.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Hidden Gems playlist, or empty list
        if the cold collection is empty.

    """
    played = set(ctx["played_file_ids"])

    # Collect known artist tag values via persistence
    known_artists: set[str] = set(
        db.tags.get_distinct_tag_values_for_files(ctx["played_file_ids"], "artist")
    )
    if not known_artists:
        logger.debug("No known artists for hidden gems, falling back to discovery-style")

    cold_ops = db.get_vectors_track_cold(ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3  # Over-fetch to compensate for artist filtering
    raw_results = cold_ops.search_similar(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Exclude played tracks
    candidates: list[dict[str, Any]] = [
        r for r in raw_results if r["file_id"] not in played
    ]

    if known_artists:
        # Batch-query artist tags for candidates, then exclude known-artist tracks
        candidate_file_ids = [r["file_id"] for r in candidates]
        candidate_artists = db.tags.get_tag_values_grouped_by_file(candidate_file_ids, "artist")

        candidates = [
            r
            for r in candidates
            if not (candidate_artists.get(r["file_id"], set()) & known_artists)
        ]

    file_ids = [r["file_id"] for r in candidates][: ctx["max_songs"]]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="hidden_gems",
            playlist_name="Hidden Gems",
            file_ids=file_ids,
        )
    ]


def build_genre_playlists(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build per-genre playlists via ANN search on genre sub-collections.

    Discovers the user's genre affinities from played tracks, then queries
    each genre's cold sub-collection for similar tracks.  Genres producing
    fewer than ``_GENRE_MIN_SONGS`` tracks are silently dropped.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        List of genre playlists (one per qualifying genre), possibly empty.

    """
    played = set(ctx["played_file_ids"])

    # Get user's genre affinities from played tracks
    genres = db.tags.get_distinct_tag_values_for_files(ctx["played_file_ids"], "genre")
    if not genres:
        logger.debug("No genre affinities found for genre playlists")
        return []

    playlists: list[NavidromePersonalPlaylistEntry] = []

    for genre in genres:
        sanitized = sanitize_genre_name(genre)
        genre_suffix = f"genre__{sanitized}"

        try:
            genre_ops = db.get_vectors_track_cold(
                ctx["backbone_id"], ctx["library_key"], collection_suffix=genre_suffix
            )

            doc_count = genre_ops.count()
            if doc_count == 0:
                continue

            nlists = compute_nlists(doc_count)
            nprobe = compute_nprobe(nlists)
            fetch_limit = ctx["max_songs"] * 2
            raw_results = genre_ops.search_similar(ctx["centroid"], fetch_limit, nprobe=nprobe)

        except Exception:
            logger.debug("Genre collection suffix '%s' not available, skipping", genre_suffix)
            continue

        # Exclude played tracks
        file_ids = [
            r["file_id"] for r in raw_results if r["file_id"] not in played
        ][: ctx["max_songs"]]

        if len(file_ids) < _GENRE_MIN_SONGS:
            continue

        display_genre = genre.title()
        playlists.append(
            NavidromePersonalPlaylistEntry(
                playlist_type="genre",
                playlist_name=f"Your {display_genre} Mix",
                file_ids=file_ids,
            )
        )

    return playlists


def build_universal_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a diversified playlist via ANN search with stride sampling.

    Unlike other playlists, this one does not exclude played tracks \u2014 it
    spreads selections across the result set for variety.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Universal playlist, or empty list
        if the cold collection is empty.

    """
    cold_ops = db.get_vectors_track_cold(ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3
    raw_results = cold_ops.search_similar(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Diversified sampling: spread across the result set instead of taking top-N
    file_ids: list[str] = []
    if raw_results:
        step = max(1, len(raw_results) // ctx["max_songs"])
        sampled = raw_results[::step][: ctx["max_songs"]]
        random.shuffle(sampled)
        file_ids = [r["file_id"] for r in sampled]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="universal",
            playlist_name="Your Mix",
            file_ids=file_ids,
        )
    ]
