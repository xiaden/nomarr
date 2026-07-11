"""Recency-weighted taste-profile computation from Navidrome play history."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, cast

import numpy as np

from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.components.tagging.tag_query_comp import get_tag_values_grouped_by_file
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import TasteProfile, TrackPlayData
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def compute_taste_profile(
    db: Database,
    user_id: str,
    top_plays: list[TrackPlayData] | None = None,
    backbone_id: str | None = None,
    half_life_days: float = 30.0,
    top_n: int = 200,
    pp_max_clusters: int = 10,
    plays: list[TrackPlayData] | None = None,
) -> TasteProfile | None:
    """Compute a recency-weighted taste profile from play data.

    Groups tracks by genre tag, builds per-genre weighted-average centroid
    clusters, then returns the top ``pp_max_clusters`` clusters sorted by
    total recency weight.

    Returns a :class:`TasteProfile` dict with ``clusters``, or ``None`` if
    insufficient play data with embeddings is available.
    """
    # Accept plays from either kwarg (prefer top_plays then plays)
    resolved_plays_raw: list[TrackPlayData] | None = top_plays or plays
    if resolved_plays_raw is None:
        resolved_plays_raw = db.app.legacy_navidrome.get_top_nd_plays(user_id, top_n)  # type: ignore[assignment]

    if not resolved_plays_raw:
        logger.info("[navidrome] No play data for user %s — cannot build taste profile", user_id)
        return None

    resolved_plays = [p for p in resolved_plays_raw if p["file_id"] is not None]
    if not resolved_plays:
        logger.info(
            "[navidrome] User %s has %d plays but none resolved to library files",
            user_id,
            len(resolved_plays_raw),
        )
        return None

    file_ids = [fid for p in resolved_plays if (fid := p["file_id"]) is not None]
    now_val = now_ms().value

    # Group file_ids by genre
    # get_tag_values_grouped_by_file returns {file_id: {genre_set}}
    file_genre_map: dict[str, set[str]] = {}
    if backbone_id:
        file_genre_map = get_tag_values_grouped_by_file(db, file_ids, "genre")

    # Invert to {genre: set[file_ids]}
    genre_to_files: dict[str, set[str]] = {}
    for fid, genres in file_genre_map.items():
        for genre in genres:
            genre_to_files.setdefault(genre, set()).add(fid)

    # Build per-genre clusters
    clusters: list[dict] = []
    for genre_label, genre_file_set in genre_to_files.items():
        genre_plays = [p for p in resolved_plays if p.get("file_id") in genre_file_set]
        if len(genre_plays) < 3:
            continue

        # Get vectors for this genre's files
        cold_ops = get_cold_namespace(db, backbone_id or "default")
        genre_file_id_list = [p["file_id"] for p in genre_plays if p["file_id"] is not None]
        vector_docs = cold_ops.get_vectors_by_file_ids(genre_file_id_list)

        vector_map = {doc["file_id"]: doc["vector"] for doc in vector_docs if "vector" in doc and doc.get("file_id")}

        paired: list[tuple[TrackPlayData, list[float]]] = []
        for play in genre_plays:
            fid = play.get("file_id")
            if fid is None:
                continue
            vec = vector_map.get(fid)
            if vec is not None:
                paired.append((play, vec))

        if not paired or len(paired) < 3:
            continue

        weights = _compute_recency_weights(
            [p for p, _ in paired],
            now_val,
            half_life_days,
        )
        centroid = _compute_weighted_centroid(
            [v for _, v in paired],
            weights,
        )
        total_weight = sum(weights)

        clusters.append(
            {
                "label": genre_label,
                "centroid": centroid,
                "track_count": len(paired),
                "total_weight": total_weight,
            }
        )

    # Add untagged cluster for files without genre
    tagged_file_ids = set().union(*genre_to_files.values()) if genre_to_files else set()
    untagged_file_ids = set(file_ids) - tagged_file_ids
    if untagged_file_ids:
        untagged_plays = [p for p in resolved_plays if p.get("file_id") in untagged_file_ids]
        if len(untagged_plays) >= 3:
            cold_ops = get_cold_namespace(db, backbone_id or "default")
            ut_file_ids = [p["file_id"] for p in untagged_plays if p["file_id"] is not None]
            ut_vector_docs = cold_ops.get_vectors_by_file_ids(ut_file_ids)
            ut_vector_map = {
                doc["file_id"]: doc["vector"] for doc in ut_vector_docs if "vector" in doc and doc.get("file_id")
            }
            ut_paired: list[tuple[TrackPlayData, list[float]]] = []
            for play in untagged_plays:
                fid = play.get("file_id")
                if fid is None:
                    continue
                vec = ut_vector_map.get(fid)
                if vec is not None:
                    ut_paired.append((play, vec))
            if len(ut_paired) >= 3:
                ut_weights = _compute_recency_weights(
                    [p for p, _ in ut_paired],
                    now_val,
                    half_life_days,
                )
                ut_centroid = _compute_weighted_centroid(
                    [v for _, v in ut_paired],
                    ut_weights,
                )
                clusters.append(
                    {
                        "label": "untagged",
                        "centroid": ut_centroid,
                        "track_count": len(ut_paired),
                        "total_weight": sum(ut_weights),
                    }
                )

    if not clusters:
        logger.info(
            "[navidrome] User %s: %d resolved tracks but no genre clusters had ≥3 vectorised songs",
            user_id,
            len(resolved_plays),
        )
        return None

    # Sort by total_weight descending, cap at pp_max_clusters
    clusters.sort(key=lambda c: c["total_weight"], reverse=True)
    clusters = clusters[:pp_max_clusters]

    return cast(
        "TasteProfile",
        {
            "user_id": user_id,
            "clusters": clusters,
            "backbone_id": backbone_id or "",
            "track_count": sum(c["track_count"] for c in clusters),
            "generated_at_ms": now_val,
        },
    )


_MS_PER_DAY = 86_400_000


def _compute_recency_weights(
    plays: list[TrackPlayData],
    now_ms_val: int,
    half_life_days: float,
) -> list[float]:
    """Compute recency-weighted scores: w_i = log(1 + playcount_i) * exp(-λ * days_since_last_play)."""
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
    """Compute L2-normalised weighted centroid of embedding vectors."""
    arr = np.asarray(vectors, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)

    centroid = np.average(arr, axis=0, weights=w)

    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    result: list[float] = centroid.tolist()
    return result
