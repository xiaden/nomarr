"""Recency-weighted taste-profile computation from Navidrome play history."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import TasteProfile, TrackPlayData
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def compute_taste_profile(
    db: Database,
    user_id: str,
    backbone_id: str,
    library_key: str,
    half_life_days: float = 30.0,
    top_n: int = 200,
) -> TasteProfile | None:
    """Compute a recency-weighted taste profile from play-count data.

    Returns a :class:`TasteProfile` dict with an L2-normalised centroid, or
    ``None`` if insufficient play data with embeddings is available.
    """
    plays: list[TrackPlayData] = db.navidrome_playcounts.get_top_plays(user_id, top_n)
    if not plays:
        logger.info("[navidrome] No play data for user %s — cannot build taste profile", user_id)
        return None

    resolved_plays = [p for p in plays if p["file_id"] is not None]
    if not resolved_plays:
        logger.info(
            "[navidrome] User %s has %d plays but none resolved to library files",
            user_id,
            len(plays),
        )
        return None

    file_ids = [fid for p in resolved_plays if (fid := p["file_id"]) is not None]
    cold_ops = db.get_vectors_track_cold(backbone_id, library_key)
    vector_docs = cold_ops.get_vectors_by_file_ids(file_ids)

    vector_map: dict[str, list[float]] = {doc["file_id"]: doc["vector"] for doc in vector_docs if "vector" in doc}

    paired: list[tuple[TrackPlayData, list[float]]] = []
    for play in resolved_plays:
        fid = play["file_id"]
        if fid is None:
            continue
        vec = vector_map.get(fid)
        if vec is not None:
            paired.append((play, vec))

    if not paired:
        logger.info(
            "[navidrome] User %s: %d resolved tracks but none have cold-vector embeddings",
            user_id,
            len(resolved_plays),
        )
        return None

    now_val = now_ms().value
    weights = _compute_recency_weights(
        [p for p, _ in paired],
        now_val,
        half_life_days,
    )
    centroid = _compute_weighted_centroid(
        [v for _, v in paired],
        weights,
    )

    logger.info(
        "[navidrome] Taste profile for user %s: %d tracks, dim=%d",
        user_id,
        len(paired),
        len(centroid),
    )

    return {
        "user_id": user_id,
        "centroid": centroid,
        "backbone_id": backbone_id,
        "library_key": library_key,
        "track_count": len(paired),
        "generated_at_ms": now_val,
    }


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
