"""Taste-profile computation from Navidrome play history.

Stateless component that builds multi-cluster recency-weighted centroid
embeddings (one per genre group) representing a user's listening
preferences.  Called by the playlist generation workflow (Part E).
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.components.tagging.tag_query_comp import get_tag_values_grouped_by_file
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import TasteCluster, TasteProfile, TrackPlayData
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_taste_profile(
    db: Database,
    user_id: str,
    top_plays: list[TrackPlayData],
    backbone_id: str,
    half_life_days: float = 30.0,
    top_n: int = 200,
    pp_max_clusters: int = 10,
) -> TasteProfile | None:
    """Compute a taste profile for *user_id* from caller-provided play data.

    Groups the user's top tracks by genre, computes a weighted centroid per
    genre group, and returns a multi-cluster taste profile with up to
    ``pp_max_clusters`` genre-scoped centroids.  When the number of clusters
    exceeds ``pp_max_clusters``, they are sorted by decreasing total recency
    weight and the lowest-weighted clusters are dropped.  Genres with fewer
    than 3 tracks are skipped.

    Steps:
    1. Slice the caller-supplied ``top_plays`` to ``top_n``.
    2. Filter to tracks that have both a ``file_id`` and a cold-vector embedding.
    3. Group resolved tracks by genre tag via ``get_tag_values_grouped_by_file``.
    4. For each genre group (>=3 tracks), compute a recency-weighted centroid:
       :math:`w_i = \\log(1+c_i) \\cdot e^{-\\lambda d_i}`.
    5. L2-normalise each per-genre centroid.
    6. Include an ``"untagged"`` cluster if untagged tracks exceed 5\\% of total
       paired tracks and have >=3 tracks.
    7. Cap the total number of clusters to ``pp_max_clusters`` (sorted by weight).

    Args:
        db: Database instance.
        user_id: Navidrome user identifier.
        top_plays: Play history provided by the caller (e.g. the Navidrome plugin).
            Each entry must include ``file_id``, ``playcount``, and ``last_played``.
        backbone_id: Backbone used for embeddings (e.g. ``"discogs_effnet"``).
        half_life_days: Recency half-life in days (default 30).
        top_n: Maximum number of top tracks to consider.
        pp_max_clusters: Maximum number of genre clusters to return (default 10).
            Clusters exceeding this cap are dropped by lowest total weight.

    Returns:
        A :class:`TasteProfile` dict with ``clusters`` (list of
        :class:`TasteCluster` dicts, one per genre group), or ``None`` if no
        valid tracks with embeddings could be found.

    """
    # Step 1: Use caller-provided play data (sliced to top_n)
    plays: list[TrackPlayData] = list(top_plays[:top_n])
    if not plays:
        logger.info("No play data for user %s — cannot build taste profile", user_id)
        return None

    # Step 2: Filter to resolved tracks (file_id is not None)
    resolved_plays = [p for p in plays if p["file_id"] is not None]
    if not resolved_plays:
        logger.info(
            "User %s has %d plays but none resolved to library files",
            user_id,
            len(plays),
        )
        return None

    # Step 3: Batch-fetch cold vectors for resolved file IDs
    file_ids = [p["file_id"] for p in resolved_plays]  # all non-None after filter
    cold_ops = get_cold_namespace(db, backbone_id)
    vector_docs = cold_ops.get_vectors_by_file_ids(file_ids)  # type: ignore[arg-type]

    # Build file_id → vector mapping
    vector_map: dict[str, list[float]] = {doc["file_id"]: doc["vector"] for doc in vector_docs if "vector" in doc}

    # Step 4: Pair plays with their vectors, dropping those without embeddings
    paired: list[tuple[TrackPlayData, list[float]]] = []
    for play in resolved_plays:
        vec = vector_map.get(play["file_id"])  # type: ignore[arg-type]
        if vec is not None:
            paired.append((play, vec))

    if not paired:
        logger.info(
            "User %s: %d resolved tracks but none have cold-vector embeddings",
            user_id,
            len(resolved_plays),
        )
        return None

    # Step 5: Batch-fetch genre tags
    genre_map = get_tag_values_grouped_by_file(
        db,
        [p["file_id"] for p, _ in paired if p["file_id"] is not None],
        "genre",
    )

    # Step 6: Group paired plays by genre
    genre_groups: dict[str, list[tuple[TrackPlayData, list[float]]]] = OrderedDict()
    untagged: list[tuple[TrackPlayData, list[float]]] = []
    for play, vec in paired:
        genres = genre_map.get(play["file_id"])  # type: ignore[arg-type]
        if genres:
            primary = sorted(genres)[0]  # deterministic: first sorted tag
            genre_groups.setdefault(primary, []).append((play, vec))
        else:
            untagged.append((play, vec))

    logger.info(
        "Genre grouping for user %s: %d genres, %d untagged tracks, %d total paired",
        user_id,
        len(genre_groups),
        len(untagged),
        len(paired),
    )

    # Step 7: Compute per-cluster centroids
    now_val = now_ms().value
    clusters: list[TasteCluster] = []
    for genre, tracks_in_group in genre_groups.items():
        if len(tracks_in_group) < 3:
            logger.debug(
                "Skipping genre '%s': only %d tracks (minimum 3)",
                genre,
                len(tracks_in_group),
            )
            continue

        group_plays = [p for p, _ in tracks_in_group]
        group_vectors = [v for _, v in tracks_in_group]
        group_weights = _compute_recency_weights(group_plays, now_val, half_life_days)
        group_centroid = _compute_weighted_centroid(group_vectors, group_weights)
        total_weight = sum(group_weights)

        clusters.append(
            {
                "label": genre,
                "centroid": group_centroid,
                "track_count": len(tracks_in_group),
                "total_weight": total_weight,
            }
        )

    # Step 8: Handle untagged tracks
    if untagged:
        if len(untagged) < 3:
            logger.debug(
                "Skipping untagged cluster for user %s: only %d untagged tracks (minimum 3)",
                user_id,
                len(untagged),
            )
        else:
            untagged_fraction = len(untagged) / len(paired)
            if untagged_fraction > 0.05:
                untagged_plays = [p for p, _ in untagged]
                untagged_vectors = [v for _, v in untagged]
                untagged_weights = _compute_recency_weights(untagged_plays, now_val, half_life_days)
                untagged_centroid = _compute_weighted_centroid(untagged_vectors, untagged_weights)
                untagged_total_weight = sum(untagged_weights)
                clusters.append(
                    {
                        "label": "untagged",
                        "centroid": untagged_centroid,
                        "track_count": len(untagged),
                        "total_weight": untagged_total_weight,
                    }
                )
            else:
                logger.info(
                    "Untagged tracks for user %s below 5%% threshold (%.1f%%) — dropping",
                    user_id,
                    untagged_fraction * 100,
                )

    # Step 9: Cap clusters to pp_max_clusters
    if len(clusters) > pp_max_clusters:
        clusters.sort(key=lambda c: c["total_weight"], reverse=True)
        dropped = clusters[pp_max_clusters:]
        clusters = clusters[:pp_max_clusters]
        logger.info(
            "Capped clusters to %d; dropped %d clusters: %s",
            pp_max_clusters,
            len(dropped),
            [c["label"] for c in dropped],
        )

    # Step 10: If no clusters formed, return None
    if not clusters:
        logger.info("No clusters formed for user %s — returning None", user_id)
        return None

    logger.info(
        "Taste profile for user %s: %d clusters, %d total tracks",
        user_id,
        len(clusters),
        len(paired),
    )
    return {
        "user_id": user_id,
        "clusters": clusters,
        "backbone_id": backbone_id,
        "track_count": len(paired),
        "generated_at_ms": now_val,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_MS_PER_DAY = 86_400_000


def _compute_recency_weights(
    plays: list[TrackPlayData],
    now_ms_val: int,
    half_life_days: float,
) -> list[float]:
    """Compute recency-weighted scores for *plays*.

    Formula per track:
        :math:`\\lambda = \\ln 2 / \\text{half\\_life\\_days}`

        :math:`d_i` = days since last play (fallback: ``half_life_days * 2``
        when ``last_played`` is ``None``)

        :math:`w_i = \\log(1 + playcount_i) \\cdot e^{-\\lambda \\cdot d_i}`

    Args:
        plays: Track play data dicts.
        now_ms_val: Current epoch-millis timestamp.
        half_life_days: Decay half-life in days.

    Returns:
        One positive weight per play in the same order.

    """
    decay_lambda = math.log(2) / half_life_days
    fallback_days = half_life_days * 2

    weights: list[float] = []
    for play in plays:
        last_ms = play["last_played"]
        if last_ms is not None:
            days_since = (now_ms_val - last_ms) / _MS_PER_DAY
        else:
            days_since = fallback_days

        w = math.log(1 + play["playcount"]) * math.exp(-decay_lambda * days_since)
        weights.append(w)

    return weights


def _compute_weighted_centroid(
    vectors: list[list[float]],
    weights: list[float],
) -> list[float]:
    """Compute L2-normalised weighted centroid of *vectors*.

    Args:
        vectors: Embedding vectors (one per track).
        weights: Corresponding positive weights.

    Returns:
        L2-normalised centroid as a plain list of floats.

    """
    arr = np.asarray(vectors, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)

    centroid = np.average(arr, axis=0, weights=w)

    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    result: list[float] = centroid.tolist()
    return result
