"""Taste-profile computation from Navidrome play history.

Stateless component that builds a recency-weighted centroid embedding
representing a user's listening preferences.  Called by the playlist
generation workflow (Part E).
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np

from nomarr.components.navidrome.navidrome_graph_comp import get_top_navidrome_plays
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import TasteProfile, TrackPlayData
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_taste_profile(
    db: Database,
    user_id: str,
    backbone_id: str,
    library_key: str,
    half_life_days: float = 30.0,
    top_n: int = 200,
) -> TasteProfile | None:
    """Compute a taste profile for *user_id* from play-count data.

    Steps:
    1. Fetch top-N most-played tracks via graph traversal.
    2. Filter to tracks that have both a ``file_id`` and a cold-vector embedding.
    3. Compute recency-weighted centroid: :math:`w_i = \\log(1+c_i) \\cdot e^{-\\lambda d_i}`.
    4. L2-normalise the centroid.

    Args:
        db: Database instance.
        user_id: Navidrome user identifier.
        backbone_id: Backbone used for embeddings (e.g. ``"discogs_effnet"``).
        library_key: ArangoDB ``_key`` of the library document.
        half_life_days: Recency half-life in days (default 30).
        top_n: Maximum number of top tracks to consider.

    Returns:
        A :class:`TasteProfile` dict, or ``None`` if no valid tracks with
        embeddings could be found.

    """
    # Step 1: Fetch top plays via graph traversal
    plays: list[TrackPlayData] = get_top_navidrome_plays(db, user_id, top_n)
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
    cold_ops = db.get_vectors_track_cold(backbone_id, library_key)
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

    # Step 5: Compute recency weights and weighted centroid
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
        "Taste profile for user %s: %d tracks, dim=%d",
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
