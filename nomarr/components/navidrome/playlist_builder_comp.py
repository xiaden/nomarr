"""Build personal playlist track lists from taste profiles and play history.

Each public function encapsulates the domain logic for one playlist type:
per-cluster ANN search, exclusion filtering, proportional interleaving
(except genre playlists, which create one playlist per cluster),
and result assembly.  ANN search uses ``get_cold_namespace(db, backbone_id)``
for vector similarity queries against each cluster's pre-computed
centroid; tag access delegates to ``tag_query_comp`` helpers.

Four builders (familiar, discovery, hidden_gems, universal) iterate
``ctx["clusters"]`` and call the module-private ``_interleave_per_cluster()``
helper to merge per-cluster results proportionally to each cluster's
``total_weight`` (largest-remainder slot allocation + round-robin
interleaving).  The genre builder instead emits one playlist entry per
qualifying cluster, so no interleaving is performed.

Every builder has the uniform signature::

    (db: Database, ctx: NavidromePersonalPlaylistContext)
        -> list[NavidromePersonalPlaylistEntry]

Builders return only ``song/_id`` values.  Navidrome nd_id
resolution is the interface layer's responsibility.
"""

from __future__ import annotations

import logging
import random
from collections import deque
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.components.tagging.tag_query_comp import (
    get_distinct_tag_values_for_files,
    get_tag_values_grouped_by_file,
)
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

#: Minimum tracks for a genre playlist to be included in the output.
_GENRE_MIN_SONGS: int = 100

#: Hard server-side cap on the number of genre playlists generated per user.
_MAX_GENRE_PLAYLISTS_CAP: int = 25


def _interleave_per_cluster(
    results_by_cluster: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
    target_size: int,
) -> list[str]:
    """Interleave results from multiple clusters proportional to weight.

    Allocates slots using the largest-remainder method, then round-robins
    across clusters in descending weight order to produce the final list.

    Args:
        results_by_cluster: Map of cluster label -> filtered ANN results.
        weights: Map of cluster label -> total_weight for proportional
            slot allocation.
        target_size: Desired playlist size (number of tracks).

    Returns:
        Flat list of ``file_id`` strings, interleaved by cluster.

    Edge cases:
        - Empty input or zero target_size returns [].
        - Single non-empty cluster returns its results up to target_size.
        - Clusters with no results are silently skipped.
        - If all clusters are exhausted before target_size is reached,
          returns whatever was collected so far.

    """
    # --- edge cases ---
    if target_size == 0 or not results_by_cluster:
        return []

    # Filter to non-empty clusters only
    non_empty: dict[str, list[dict[str, Any]]] = {label: res for label, res in results_by_cluster.items() if res}
    if not non_empty:
        return []

    # Single-cluster shortcut: no interleaving needed
    if len(non_empty) == 1:
        label = next(iter(non_empty))
        return [r["file_id"] for r in non_empty[label]][:target_size]

    # === slot allocation (largest-remainder method) ===
    total_weight = sum(weights.get(label, 0.0) for label in non_empty)

    if total_weight <= 0:
        # Fallback: even split across all non-empty clusters
        base = target_size // len(non_empty)
        rem = target_size % len(non_empty)
        sorted_labels = sorted(non_empty)
        slots: dict[str, int] = {}
        for i, label in enumerate(sorted_labels):
            slots[label] = base + (1 if i < rem else 0)
    else:
        # Compute exact quota per cluster, take floor as base allocation
        exact: dict[str, float] = {}
        for label in non_empty:
            exact[label] = weights[label] / total_weight * target_size

        slots = {label: int(exact[label]) for label in non_empty}
        allocated = sum(slots.values())
        remainder = target_size - allocated

        if remainder > 0:
            # Sort by fractional part descending (largest-remainder)
            for label in sorted(
                non_empty,
                key=lambda cl: (exact[cl] - int(exact[cl]), weights.get(cl, 0.0)),
                reverse=True,
            ):
                if remainder <= 0:
                    break
                slots[label] += 1
                remainder -= 1

    # === round-robin interleaving (descending weight order) ===
    order = sorted(non_empty, key=lambda cl: weights.get(cl, 0.0), reverse=True)

    # Working copies so we don't mutate the caller's lists
    pools: dict[str, deque[dict[str, Any]]] = {label: deque(non_empty[label]) for label in order}
    remaining = dict(slots)

    result: list[str] = []
    while len(result) < target_size:
        advanced = False
        for label in order:
            if remaining.get(label, 0) <= 0:
                continue
            if not pools[label]:
                continue
            # Take next result preserving ANN rank order within this cluster
            result.append(pools[label].popleft()["file_id"])
            remaining[label] -= 1
            advanced = True

        if not advanced:
            # All clusters exhausted before reaching target_size
            break

    return result


# ------------------------------------------------------------------
# Public builder functions
# ------------------------------------------------------------------


def build_familiar_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Familiar playlist: ANN search biased toward played tracks.

    Uses per-cluster taste centroids for ANN search on the global cold
    collection, then *includes only* played tracks that appear in the
    results per cluster.  Results are interleaved across clusters
    proportionally to cluster weight.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Familiar playlist, or empty list
        if no played tracks appear in ANN results or the cold collection is empty.

    """
    played = set(ctx["played_file_ids"])
    if not played:
        return []

    cold_ops = get_cold_namespace(db, ctx["backbone_id"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    # Over-fetch: most results won't be in the played set
    fetch_limit = ctx["max_songs"] * 5

    results_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for cluster in ctx["clusters"]:
        raw = cold_ops.ann_search(cluster["centroid"], fetch_limit, nprobe=nprobe)
        filtered = [r for r in raw if r["file_id"] in played]
        if filtered:
            results_by_cluster[cluster["label"]] = filtered

    weights = {c["label"]: c["total_weight"] for c in ctx["clusters"]}
    file_ids = _interleave_per_cluster(results_by_cluster, weights, ctx["max_songs"])

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

    Uses per-cluster taste centroids for ANN search, excluding played
    tracks from each cluster's results.  Results are interleaved across
    clusters proportionally to cluster weight.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Discovery playlist, or empty list
        if the cold collection is empty.

    """
    played = set(ctx["played_file_ids"])

    cold_ops = get_cold_namespace(db, ctx["backbone_id"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 2

    results_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for cluster in ctx["clusters"]:
        raw = cold_ops.ann_search(cluster["centroid"], fetch_limit, nprobe=nprobe)
        filtered = [r for r in raw if r["file_id"] not in played]
        if filtered:
            results_by_cluster[cluster["label"]] = filtered

    weights = {c["label"]: c["total_weight"] for c in ctx["clusters"]}
    file_ids = _interleave_per_cluster(results_by_cluster, weights, ctx["max_songs"])

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

    Uses per-cluster taste centroids for ANN search, excluding played
    tracks and tracks by known artists per cluster.  Results are
    interleaved across clusters proportionally to cluster weight.

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

    cold_ops = get_cold_namespace(db, ctx["backbone_id"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3  # Over-fetch to compensate for artist filtering

    # Per-cluster: ANN search → exclude played → exclude known-artist tracks
    results_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for cluster in ctx["clusters"]:
        raw = cold_ops.ann_search(cluster["centroid"], fetch_limit, nprobe=nprobe)
        candidates = [r for r in raw if r["file_id"] not in played]
        if not candidates:
            continue

        if known_artists:
            candidate_file_ids = [r["file_id"] for r in candidates]
            candidate_artists = get_tag_values_grouped_by_file(db, candidate_file_ids, "artist")
            candidates = [r for r in candidates if not (candidate_artists.get(r["file_id"], set()) & known_artists)]

        if candidates:
            results_by_cluster[cluster["label"]] = candidates

    weights = {c["label"]: c["total_weight"] for c in ctx["clusters"]}
    file_ids = _interleave_per_cluster(results_by_cluster, weights, ctx["max_songs"])

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

    Uses per-cluster taste centroids for ANN search, stride-samples
    within each cluster, then interleaves across clusters proportionally
    to cluster weight.  The final list is shuffled for variety.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        Single-element list with the Universal playlist, or empty list
        if the cold collection is empty.

    """
    cold_ops = get_cold_namespace(db, ctx["backbone_id"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3

    results_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for cluster in ctx["clusters"]:
        raw = cold_ops.ann_search(cluster["centroid"], fetch_limit, nprobe=nprobe)
        if raw:
            step = max(1, len(raw) // ctx["max_songs"])
            sampled = raw[::step]
            if sampled:
                results_by_cluster[cluster["label"]] = sampled

    weights = {c["label"]: c["total_weight"] for c in ctx["clusters"]}
    file_ids = _interleave_per_cluster(results_by_cluster, weights, ctx["max_songs"])

    # Final shuffle for variety
    if file_ids:
        random.shuffle(file_ids)

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
    """Build per-genre playlists from pre-computed taste profile clusters.

    Consumes the pre-computed clusters from the user's taste profile.
    For each cluster, performs a genre-filtered ANN search using the
    cluster's pre-computed centroid.  Clusters with fewer than
    ``_GENRE_MIN_SONGS`` results are skipped.

    Args:
        db: Database instance.
        ctx: Personal playlist context.

    Returns:
        One ``NavidromePersonalPlaylistEntry`` per qualifying genre,
        or an empty list if there are no clusters or the cold collection is empty.

    """
    clusters = ctx["clusters"]
    if not clusters:
        return []

    cold_ops = get_cold_namespace(db, ctx["backbone_id"])
    doc_count = cold_ops.count()
    if doc_count == 0:
        return []

    nlists = compute_nlists(doc_count)
    nprobe = compute_nprobe(nlists)
    fetch_limit = ctx["max_songs"] * 3  # over-fetch to compensate for in-traversal genre filter

    # Sort clusters by total_weight descending, cap at effective_max
    effective_max = min(ctx["max_genre_playlists"], _MAX_GENRE_PLAYLISTS_CAP)
    sorted_clusters = sorted(clusters, key=lambda c: c["total_weight"], reverse=True)[:effective_max]

    playlists: list[NavidromePersonalPlaylistEntry] = []
    for cluster in sorted_clusters:
        raw_results = cold_ops.ann_search(
            cluster["centroid"],
            fetch_limit,
            nprobe,
            filter={"genres": cluster["label"]},
        )

        if len(raw_results) < _GENRE_MIN_SONGS:
            logger.debug(
                "Genre %r returned only %d results (<%d); skipping",
                cluster["label"],
                len(raw_results),
                _GENRE_MIN_SONGS,
            )
            continue

        file_ids = [r["file_id"] for r in raw_results][: ctx["max_songs"]]
        playlists.append(
            NavidromePersonalPlaylistEntry(
                playlist_type=f"genre_{cluster['label'].lower()}",
                playlist_name=f"Your {cluster['label'].title()} Mix",
                file_ids=file_ids,
            )
        )

    return playlists
