"""Build personal playlist track lists from taste profiles and play history.

Each public function encapsulates the domain logic for one playlist type:
ANN search, exclusion filtering, and result assembly. ANN search uses
``get_cold_namespace(db, ...)`` for vector similarity queries; tag access
delegates to ``tag_query_comp`` helpers.

Every builder has the uniform signature::

    (db: Database, ctx: NavidromePersonalPlaylistContext)
        -> list[NavidromePersonalPlaylistEntry]

Builders return only ``library_files/_id`` values.  Navidrome nd_id
resolution is the interface layer's responsibility.
"""

from __future__ import annotations

import logging
import math
import random
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.components.tagging.tag_query_comp import (
    get_distinct_tag_values_for_files,
    get_tag_values_grouped_by_file,
)
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.time_helper import now_ms
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

#: Minimum tracks for a genre playlist to be included in the output.
_GENRE_MIN_SONGS: int = 100

#: Hard server-side cap on the number of genre playlists generated per user.
_MAX_GENRE_PLAYLISTS_CAP: int = 25

#: Milliseconds per day — used for recency weight computation.
_MS_PER_DAY: float = 86_400_000.0


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

    cold_ops = get_cold_namespace(db, ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    # Over-fetch: most results won't be in the played set
    fetch_limit = ctx["max_songs"] * 5
    raw_results = cold_ops.ann_search(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Keep only tracks the user has played, preserving ANN ranking
    file_ids = [r["file_id"] for r in raw_results if r["file_id"] in played][: ctx["max_songs"]]

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

    cold_ops = get_cold_namespace(db, ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 2
    raw_results = cold_ops.ann_search(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Exclude played tracks
    file_ids = [r["file_id"] for r in raw_results if r["file_id"] not in played][: ctx["max_songs"]]

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
    known_artists: set[str] = set(get_distinct_tag_values_for_files(db, ctx["played_file_ids"], "artist"))
    if not known_artists:
        logger.debug("No known artists for hidden gems, falling back to discovery-style")

    cold_ops = get_cold_namespace(db, ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3  # Over-fetch to compensate for artist filtering
    raw_results = cold_ops.ann_search(ctx["centroid"], fetch_limit, nprobe=nprobe)

    # Exclude played tracks
    candidates: list[dict[str, Any]] = [r for r in raw_results if r["file_id"] not in played]

    if known_artists:
        # Batch-query artist tags for candidates, then exclude known-artist tracks
        candidate_file_ids = [r["file_id"] for r in candidates]
        candidate_artists = get_tag_values_grouped_by_file(db, candidate_file_ids, "artist")

        candidates = [r for r in candidates if not (candidate_artists.get(r["file_id"], set()) & known_artists)]

    file_ids = [r["file_id"] for r in candidates][: ctx["max_songs"]]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="hidden_gems",
            playlist_name="Hidden Gems",
            file_ids=file_ids,
        )
    ]


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
    cold_ops = get_cold_namespace(db, ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3
    raw_results = cold_ops.ann_search(ctx["centroid"], fetch_limit, nprobe=nprobe)

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


def build_genre_playlists(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build per-genre playlists using per-genre recency-weighted centroids.

    For each genre represented in the user's play history, this builder:

    1. Computes a **genre-specific centroid** from only the played tracks
       tagged with that genre, using the same recency weighting formula as
       :func:`~nomarr.components.navidrome.taste_profile_comp.compute_taste_profile`.
    2. Ranks genres by their total recency-weighted affinity score.
    3. Takes the top ``ctx["max_genre_playlists"]`` genres (hard-capped at
       :data:`_MAX_GENRE_PLAYLISTS_CAP`).
    4. For each top genre, performs a genre-filtered ANN search with the
       genre-specific centroid.  Genres that return fewer than
       :data:`_GENRE_MIN_SONGS` candidates are skipped.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        One ``NavidromePersonalPlaylistEntry`` per qualifying genre,
        or an empty list if there is no play history with genre data.

    """
    played_tracks = ctx["played_tracks"]
    if not played_tracks:
        return []

    played_file_ids = ctx["played_file_ids"]

    cold_ops = get_cold_namespace(db, ctx["backbone_id"], ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    # Fetch cold vectors for all played tracks in one batch
    vector_docs = cold_ops.get_vectors_by_file_ids(played_file_ids)
    vector_map: dict[str, list[float]] = {doc["file_id"]: doc["vector"] for doc in vector_docs if "vector" in doc}
    if not vector_map:
        return []

    # Fetch genre tags for played tracks in one batch
    file_genres = get_tag_values_grouped_by_file(db, played_file_ids, "genre")

    # Pre-compute recency decay constants
    now_ms_val = now_ms().value
    half_life = ctx["half_life_days"]
    decay_lambda = math.log(2) / half_life
    fallback_days = half_life * 2

    # Build genre → [(recency_weight, vector)] map
    genre_data: dict[str, list[tuple[float, list[float]]]] = {}
    for play in played_tracks:
        fid = play["file_id"]
        if fid is None or fid not in vector_map:
            continue
        vec = vector_map[fid]

        last_ms = play["last_played"]
        days_since = (now_ms_val - last_ms) / _MS_PER_DAY if last_ms is not None else fallback_days
        weight = math.log(1 + play["playcount"]) * math.exp(-decay_lambda * days_since)

        for genre in file_genres.get(fid, set()):
            genre_data.setdefault(genre, []).append((weight, vec))

    if not genre_data:
        logger.debug("No genre affinities found for user; skipping genre playlists")
        return []

    # Sort genres by total affinity weight, take top N
    effective_max = min(ctx["max_genre_playlists"], _MAX_GENRE_PLAYLISTS_CAP)
    genre_affinity = {g: sum(w for w, _ in wv) for g, wv in genre_data.items()}
    top_genres = sorted(genre_affinity, key=lambda g: genre_affinity[g], reverse=True)[:effective_max]

    # Compute L2-normalized per-genre centroid for each top genre
    genre_centroids: dict[str, list[float]] = {}
    for genre in top_genres:
        wv_pairs = genre_data[genre]
        arr = np.asarray([v for _, v in wv_pairs], dtype=np.float64)
        w_arr = np.asarray([w for w, _ in wv_pairs], dtype=np.float64)
        centroid = np.average(arr, axis=0, weights=w_arr)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        genre_centroids[genre] = centroid.tolist()

    # ANN search per genre using its specific centroid
    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3  # over-fetch to compensate for in-traversal genre filter

    playlists: list[NavidromePersonalPlaylistEntry] = []
    for genre in top_genres:
        genre_centroid = genre_centroids[genre]
        raw_results = cold_ops.ann_search(
            genre_centroid,
            fetch_limit,
            nprobe,
            filter={"genres": genre},
        )

        if len(raw_results) < _GENRE_MIN_SONGS:
            logger.debug("Genre %r returned only %d results (<%d); skipping", genre, len(raw_results), _GENRE_MIN_SONGS)
            continue

        file_ids = [r["file_id"] for r in raw_results][: ctx["max_songs"]]
        playlists.append(
            NavidromePersonalPlaylistEntry(
                playlist_type=f"genre_{genre.lower()}",
                playlist_name=f"Your {genre.title()} Mix",
                file_ids=file_ids,
            )
        )

    return playlists
