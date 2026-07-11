"""Personal playlist builders from taste profiles and play history.

Each public function builds one playlist type via ANN search against the
cold vector collection.  Builders return ``library_files/_id`` values;
nd_id resolution is the interface layer's responsibility.
"""

from __future__ import annotations

import logging
import math
import random
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.time_helper import now_ms
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_GENRE_MIN_SONGS: int = 100
_MAX_GENRE_PLAYLISTS_CAP: int = 25
_MS_PER_DAY: float = 86_400_000.0


# ------------------------------------------------------------------
# Shared ANN search helper
# ------------------------------------------------------------------


def _ann_search_cold(
    db: Database,
    backbone_id: str,
    library_key: str,
    centroid: list[float],
    max_songs: int,
    fetch_multiplier: int,
) -> list[dict[str, Any]] | None:
    """Run ANN search on cold vectors; returns results or ``None`` if empty."""
    cold_ops = get_cold_namespace(db, backbone_id, collection_suffix=library_key)
    doc_count = cold_ops.count()
    if doc_count == 0:
        return None

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = max_songs * fetch_multiplier
    return cast("list[dict[str, Any]]", cold_ops.ann_search(centroid, fetch_limit, nprobe=nprobe))


def _search_all_clusters(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
    fetch_multiplier: int,
) -> list[dict[str, Any]] | None:
    """Run ANN search across every taste cluster and combine results deduplicated.
    Returns ``None`` only when every cluster search returned ``None`` (empty collection).
    Returns ``[]`` when searches ran but produced zero results.
    """
    seen: set[str] = set()
    all_results: list[dict[str, Any]] = []
    any_searched = False
    for cluster in ctx["clusters"]:
        raw = _ann_search_cold(
            db,
            ctx["backbone_id"],
            ctx["library_key"],
            cluster["centroid"],
            ctx["max_songs"],
            fetch_multiplier=fetch_multiplier,
        )
        if raw is None:
            continue
        any_searched = True
        for item in raw:
            fid = item.get("file_id")
            if fid is not None and fid not in seen:
                seen.add(fid)
                all_results.append(item)
    if not any_searched:
        return None
    return all_results


def build_familiar_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Familiar playlist: ANN search biased toward played tracks.

    Only tracks the user has already played that appear in ANN results
    are included, preserving ANN ranking order.
    """
    played = set(ctx["played_file_ids"])
    if not played:
        return []

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=5)
    if raw_results is None:
        return []

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
    """Build a Discovery playlist: ANN search excluding played tracks."""
    played = set(ctx["played_file_ids"])

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=2)
    if raw_results is None:
        return []

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
    """
    played = set(ctx["played_file_ids"])

    known_artists: set[str] = set(db.tags.get_distinct_tag_values_for_files(ctx["played_file_ids"], "artist"))
    if not known_artists:
        logger.debug("[navidrome] No known artists for hidden gems, falling back to discovery-style")

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=3)
    if raw_results is None:
        return []

    candidates: list[dict[str, Any]] = [r for r in raw_results if r["file_id"] not in played]

    if known_artists:
        candidate_file_ids = [r["file_id"] for r in candidates]
        candidate_artists = db.tags.get_tag_values_grouped_by_file(candidate_file_ids, "artist")
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

    Spreads selections across the result set for variety instead of
    taking the top-N results.
    """
    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=3)
    if raw_results is None:
        return []

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

    For each genre in the user's play history, computes a genre-specific
    centroid from played tracks weighted by recency, then runs a
    genre-filtered ANN search. Genres with fewer than
    :data:`_GENRE_MIN_SONGS` results are skipped.
    """
    played_tracks = ctx["played_tracks"]
    if not played_tracks:
        return []

    played_file_ids = ctx["played_file_ids"]

    cold_ops = get_cold_namespace(db, ctx["backbone_id"], collection_suffix=ctx["library_key"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    vector_docs = cold_ops.get_vectors_by_file_ids(played_file_ids)
    vector_map: dict[str, list[float]] = {doc["file_id"]: doc["vector"] for doc in vector_docs if "vector" in doc}
    if not vector_map:
        return []

    # Fetch genre tags for played tracks in one batch
    file_genres = db.tags.get_tag_values_grouped_by_file(played_file_ids, "genre")

    now_ms_val = now_ms().value
    half_life = ctx["half_life_days"]
    decay_lambda = math.log(2) / half_life
    fallback_days = half_life * 2

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
        logger.debug("[navidrome] No genre affinities found for user; skipping genre playlists")
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

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3

    playlists: list[NavidromePersonalPlaylistEntry] = []
    for genre in top_genres:
        genre_centroid = genre_centroids[genre]
        raw_results = cold_ops.search_similar_by_genre(genre_centroid, genre, fetch_limit, nprobe)

        if len(raw_results) < _GENRE_MIN_SONGS:
            logger.debug(
                "[navidrome] Genre %r returned only %d results (<%d); skipping",
                genre,
                len(raw_results),
                _GENRE_MIN_SONGS,
            )
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


def _interleave_per_cluster(
    results: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
    target_size: int,
) -> list[str]:
    """Interleave items from clusters proportionally by weight.

    Uses largest-remainder (Hamilton) allocation for proportional quotas,
    then round-robins in descending weight order up to each cluster's quota.

    Args:
        results: Mapping from cluster key to list of result dicts (each
            containing a ``"file_id"`` or ``"_id"`` key).
        weights: Mapping from cluster key to relative weight.
        target_size: Maximum number of items to return.

    Returns:
        Flat list of ``file_id`` strings interleaved from each cluster.

    """
    if target_size <= 0:
        return []
    if not results or not weights:
        return []

    total_weight = sum(weights.values())
    if total_weight <= 0:
        # Even split across all keys (sorted alphabetically for determinism)
        even_keys = sorted(results)
        if not even_keys:
            return []
        base = target_size // len(even_keys)
        remainder = target_size % len(even_keys)
        quotas = {k: base + (1 if i < remainder else 0) for i, k in enumerate(even_keys)}
    else:
        # Largest remainder (Hamilton) proportional allocation
        exact_quotas = {key: target_size * weights.get(key, 0) / total_weight for key in results}
        quotas = {key: int(exact) for key, exact in exact_quotas.items()}
        allocated = sum(quotas.values())
        remaining = target_size - allocated
        if remaining > 0:
            # Sort by fractional part descending, give leftover slots
            keys_by_frac = sorted(
                quotas,
                key=lambda k: exact_quotas[k] - int(exact_quotas[k]),
                reverse=True,
            )
            for i in range(remaining):
                quotas[keys_by_frac[i]] += 1

    # Extract file IDs and build ready queues
    clusters: dict[str, list[str]] = {}
    for key, items in results.items():
        if not items:
            clusters[key] = []
            continue
        file_ids: list[str] = []
        for item in items:
            fid = item.get("file_id") or item.get("_id")
            if isinstance(fid, str):
                file_ids.append(fid)
        clusters[key] = file_ids

    if all(len(v) == 0 for v in clusters.values()):
        return []

    # Proportional round-robin — each cluster yields at most its quota
    output: list[str] = []
    taken: dict[str, int] = dict.fromkeys(clusters, 0)
    indices: dict[str, int] = dict.fromkeys(clusters, 0)
    while len(output) < target_size:
        any_progress = False
        for key in sorted(clusters, key=lambda k: -weights.get(k, 0)):
            if len(output) >= target_size:
                break
            if taken[key] >= quotas.get(key, target_size):
                continue
            cluster = clusters[key]
            idx = indices[key]
            if idx >= len(cluster):
                continue
            output.append(cluster[idx])
            indices[key] = idx + 1
            taken[key] += 1
            any_progress = True
        if not any_progress:
            break
    return output
