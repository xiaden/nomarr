"""Personal playlist builders from taste profiles and play history.

Each public function builds one playlist type via ANN search against the
cold vector collection.  Search results arrive as typed
:class:`~nomarr.helpers.dataclasses.vector_dataclass.VectorMatch` values
carrying a natural
:class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`;
each match is adapted back to its transport file handle through authoritative
``db.library`` at this component boundary.  Builders return ``file_id`` strings;
nd_id resolution is the interface layer's responsibility.
"""

from __future__ import annotations

import logging
import math
import random
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.tagging.tag_query_comp import (
    get_distinct_tag_values_for_files,
    get_tag_values_grouped_by_file,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.vector_dataclass import VectorMatch
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_GENRE_MIN_SONGS: int = 100
_MAX_GENRE_PLAYLISTS_CAP: int = 25
_MS_PER_DAY: float = 86_400_000.0


# ------------------------------------------------------------------
# Shared ANN search helper
# ------------------------------------------------------------------


def _match_to_file_id(db: Database, match: VectorMatch) -> int | None:
    """Adapt a result's natural ``SongIdentity`` back to its transport file id.

    Authoritative reverse lookup through ``db.library`` (same pattern as the
    vector search service and similar-track workflow): locate the song by its
    owning library's natural ``(name, root_path)`` key plus ``normalized_path``.
    No integer storage id enters ``MlDb``.
    """
    song_obj = db.library.get_song_by_normalized_path(
        match.song.normalized_path,
        Library(name=match.song.library.name, root_path=match.song.library.root_path or ""),
    )
    return song_obj.song_id if song_obj is not None else None


def _ann_search_cold(
    db: Database,
    backbone_id: str,
    centroid: list[float],
    max_songs: int,
    fetch_multiplier: int,
) -> tuple[VectorMatch, ...] | None:
    """Run ANN search on cold vectors; returns matches or ``None`` if empty."""
    counts = db.ml.embedding_counts(backbone_id)
    if counts.cold_count == 0:
        return None

    fetch_limit = max_songs * fetch_multiplier
    return db.ml.search_similar_vectors(
        backbone_id,
        centroid,
        limit=fetch_limit,
    )


def _search_all_clusters(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
    fetch_multiplier: int,
) -> list[VectorMatch] | None:
    """Run ANN search across every taste cluster and combine results deduplicated.
    Returns ``None`` only when every cluster search returned ``None`` (empty collection).
    Returns ``[]`` when searches ran but produced zero results.
    """
    seen: set[SongIdentity] = set()
    all_results: list[VectorMatch] = []
    any_searched = False
    for cluster in ctx["clusters"]:
        raw = _ann_search_cold(
            db,
            ctx["backbone_id"],
            cluster["centroid"],
            ctx["max_songs"],
            fetch_multiplier=fetch_multiplier,
        )
        if raw is None:
            continue
        any_searched = True
        for match in raw:
            if match.song not in seen:
                seen.add(match.song)
                all_results.append(match)
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
    played = {int(fid) for fid in ctx["played_file_ids"]}
    if not played:
        return []

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=5)
    if raw_results is None:
        return []

    file_ids: list[str] = []
    for match in raw_results:
        if len(file_ids) >= ctx["max_songs"]:
            break
        fid = _match_to_file_id(db, match)
        if fid is not None and fid in played:
            file_ids.append(str(fid))

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="familiar",
            playlist_name="Your Favorites",
            file_ids=file_ids,
        ),
    ]


def build_discovery_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Discovery playlist: ANN search excluding played tracks."""
    played = {int(fid) for fid in ctx["played_file_ids"]}

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=2)
    if raw_results is None:
        return []

    file_ids: list[str] = []
    for match in raw_results:
        if len(file_ids) >= ctx["max_songs"]:
            break
        fid = _match_to_file_id(db, match)
        if fid is not None and fid not in played:
            file_ids.append(str(fid))

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="discovery",
            playlist_name="Discover Weekly",
            file_ids=file_ids,
        ),
    ]


def build_hidden_gems_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Hidden Gems playlist: ANN search excluding known-artist tracks.

    Filters out tracks by artists the user has already listened to,
    surfacing music from unfamiliar artists near the taste centroid.
    """
    played = {int(fid) for fid in ctx["played_file_ids"]}

    known_artists: set[str] = set(
        get_distinct_tag_values_for_files(db, [int(fid) for fid in ctx["played_file_ids"]], "artist")
    )
    if not known_artists:
        logger.debug("[navidrome] No known artists for hidden gems, falling back to discovery-style")

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=3)
    if raw_results is None:
        return []

    # Adapt results to file handles and exclude played tracks.
    candidates: list[tuple[VectorMatch, int]] = []
    for match in raw_results:
        fid = _match_to_file_id(db, match)
        if fid is not None and fid not in played:
            candidates.append((match, fid))

    if known_artists:
        candidate_file_ids = [fid for _, fid in candidates]
        candidate_artists = get_tag_values_grouped_by_file(db, candidate_file_ids, "artist")
        candidates = [
            (match, fid) for match, fid in candidates if not (candidate_artists.get(fid, set()) & known_artists)
        ]

    file_ids = [str(fid) for _, fid in candidates][: ctx["max_songs"]]

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="hidden_gems",
            playlist_name="Hidden Gems",
            file_ids=file_ids,
        ),
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

    # Adapt matches to transport file ids (un-mappable matches are dropped).
    adapted_file_ids: list[str] = []
    for match in raw_results:
        fid = _match_to_file_id(db, match)
        if fid is not None:
            adapted_file_ids.append(str(fid))

    file_ids: list[str] = []
    if adapted_file_ids:
        step = max(1, len(adapted_file_ids) // ctx["max_songs"])
        sampled = adapted_file_ids[::step][: ctx["max_songs"]]
        random.shuffle(sampled)
        file_ids = sampled

    return [
        NavidromePersonalPlaylistEntry(
            playlist_type="universal",
            playlist_name="Your Mix",
            file_ids=file_ids,
        ),
    ]


def build_genre_playlists(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build per-genre playlists using per-genre recency-weighted centroids.

    For each genre in the user's play history, computes a genre-specific
    centroid from played tracks weighted by recency, then runs an ANN
    search.  Genre filtering is not supported in PostgreSQL yet, so the
    search is performed without it.  Genres with fewer than
    :data:`_GENRE_MIN_SONGS` results are skipped.
    """
    played_tracks = ctx["played_tracks"]
    if not played_tracks:
        return []

    played_file_ids = ctx["played_file_ids"]

    counts = db.ml.embedding_counts(ctx["backbone_id"])
    if counts.cold_count == 0:
        return []

    # Resolve each played file handle to its natural SongIdentity via
    # db.library and read the cold-tier stored vector as a SongVector via
    # db.ml. Only authoritative domain values are consumed; no raw song_id /
    # embedding row access remains.
    vector_map: dict[int, list[float]] = {}
    for fid_str in played_file_ids:
        fid = int(fid_str)
        if fid in vector_map:
            continue
        song = db.library.resolve_song_identity(fid)
        if song is not None:
            song_vector = db.ml.get_song_vector(ctx["backbone_id"], song)
            if song_vector is not None:
                vector_map[fid] = list(song_vector.vector)

    if not vector_map:
        return []

    # Fetch genre tags for played tracks in one batch
    file_genres = get_tag_values_grouped_by_file(db, [int(fid) for fid in played_file_ids], "genre")

    now_ms_val = now_ms().value
    half_life = ctx["half_life_days"]
    decay_lambda = math.log(2) / half_life
    fallback_days = half_life * 2

    genre_data: dict[str, list[tuple[float, list[float]]]] = {}
    for play in played_tracks:
        pid = play["file_id"]
        if pid is None or pid not in vector_map:
            continue
        vec = vector_map[pid]

        last_ms = play["last_played"]
        days_since = (now_ms_val - last_ms) / _MS_PER_DAY if last_ms is not None else fallback_days
        weight = math.log(1 + play["playcount"]) * math.exp(-decay_lambda * days_since)

        for genre in file_genres.get(pid, set()):
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

    fetch_limit = ctx["max_songs"] * 3

    playlists: list[NavidromePersonalPlaylistEntry] = []
    for genre in top_genres:
        genre_centroid = genre_centroids[genre]

        # Genre filtering is not supported in PostgreSQL yet; search without it.
        raw_results = db.ml.search_similar_vectors(
            ctx["backbone_id"],
            genre_centroid,
            limit=fetch_limit,
        )

        if len(raw_results) < _GENRE_MIN_SONGS:
            logger.debug(
                "[navidrome] Genre %r returned only %d results (<%d); skipping",
                genre,
                len(raw_results),
                _GENRE_MIN_SONGS,
            )
            continue

        # Adapt typed matches back to transport file handles (un-mappable dropped).
        file_ids: list[str] = []
        for match in raw_results:
            if len(file_ids) >= ctx["max_songs"]:
                break
            match_fid = _match_to_file_id(db, match)
            if match_fid is not None:
                file_ids.append(str(match_fid))

        playlists.append(
            NavidromePersonalPlaylistEntry(
                playlist_type=f"genre_{genre.lower()}",
                playlist_name=f"Your {genre.title()} Mix",
                file_ids=file_ids,
            ),
        )

    return playlists


def _interleave_per_cluster(
    results: dict[str, list[dict]],
    weights: dict[str, float],
    target_size: int,
) -> list[str]:
    """Interleave items from clusters proportionally by weight.

    Uses largest-remainder (Hamilton) allocation for proportional quotas,
    then round-robins in descending weight order up to each cluster's quota.

    Args:
        results: Mapping from cluster key to list of result dicts (each
            containing a ``"file_id"`` or ``"id"`` key).
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
            fid = item.get("file_id") or item.get("id")
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
