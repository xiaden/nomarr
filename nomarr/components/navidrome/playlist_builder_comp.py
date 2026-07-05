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
    across clusters in descending weight order.
    """
    if target_size == 0 or not results_by_cluster:
        return []

    non_empty: dict[str, list[dict[str, Any]]] = {label: res for label, res in results_by_cluster.items() if res}
    if not non_empty:
        return []

    if len(non_empty) == 1:
        label = next(iter(non_empty))
        return [r["file_id"] for r in non_empty[label]][:target_size]

    total_weight = sum(weights.get(label, 0.0) for label in non_empty)

    if total_weight <= 0:
        base = target_size // len(non_empty)
        rem = target_size % len(non_empty)
        sorted_labels = sorted(non_empty)
        slots: dict[str, int] = {}
        for i, label in enumerate(sorted_labels):
            slots[label] = base + (1 if i < rem else 0)
    else:
        exact: dict[str, float] = {}
        for label in non_empty:
            exact[label] = weights[label] / total_weight * target_size

        slots = {label: int(exact[label]) for label in non_empty}
        allocated = sum(slots.values())
        remainder = target_size - allocated

        if remainder > 0:
            for label in sorted(
                non_empty,
                key=lambda cl: (exact[cl] - int(exact[cl]), weights.get(cl, 0.0)),
                reverse=True,
            ):
                if remainder <= 0:
                    break
                slots[label] += 1
                remainder -= 1

    order = sorted(non_empty, key=lambda cl: weights.get(cl, 0.0), reverse=True)

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
            result.append(pools[label].popleft()["file_id"])
            remaining[label] -= 1
            advanced = True

        if not advanced:
            break

    return result


# Public builder functions


def build_familiar_playlist(
    db: Database,
    ctx: NavidromePersonalPlaylistContext,
) -> list[NavidromePersonalPlaylistEntry]:
    """Build a Familiar playlist: ANN search biased toward played tracks.

    Uses per-cluster taste centroids, including only played tracks in results.
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

    Uses per-cluster taste centroids with played-track exclusion.
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
    """Build a Hidden Gems playlist: ANN search excluding played and known-artist tracks."""
    played = set(ctx["played_file_ids"])
    known_artists: set[str] = set(get_distinct_tag_values_for_files(db, ctx["played_file_ids"], "artist"))
    if not known_artists:
        logger.debug("No known artists for hidden gems, falling back to discovery-style")

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
    """Build a diversified Universal playlist via ANN search with stride sampling."""
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

    Skips clusters with fewer than ``_GENRE_MIN_SONGS`` results.
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
    fetch_limit = ctx["max_songs"] * 3

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
