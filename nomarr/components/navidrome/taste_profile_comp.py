"""Recency-weighted taste-profile computation from caller-provided play history (Navidrome plugin/request boundary)."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, cast

import numpy as np

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
    pp_max_clusters: int = 10,
    plays: list[TrackPlayData] | None = None,
) -> TasteProfile | None:
    """Compute a recency-weighted taste profile from caller-provided play data.

    Play history is REQUIRED from the caller (Navidrome plugin / API request
    boundary); Nomarr never reads it from local persistence. Groups tracks by
    genre tag, builds per-genre weighted-average centroid clusters, then
    returns the top ``pp_max_clusters`` clusters sorted by total recency
    weight.

    Each play's ``file_id`` handle is resolved to a natural
    :class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
    through authoritative ``db.library`` and its embedding read as a domain
    :class:`~nomarr.helpers.dataclasses.vector_dataclass.SongVector` via the
    typed ``db.ml.get_song_vector`` intent — never a raw persistence row or
    storage key.

    Returns a :class:`TasteProfile` dict with ``clusters``, or ``None`` if no
    play data was provided or insufficient plays with embeddings are available.
    """
    # Accept plays from either kwarg (prefer top_plays then plays)
    resolved_plays_raw: list[TrackPlayData] | None = top_plays or plays
    if resolved_plays_raw is None:
        logger.info(
            "[navidrome] No play data provided for user %s — cannot build taste profile",
            user_id,
        )
        return None

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
    resolved_backbone = backbone_id or "default"

    # Memoised per-file resolution: a play's file handle is bridged to its
    # natural SongIdentity via db.library, then the cold-tier stored vector is
    # read as a SongVector via db.ml. Only the authoritative domain values are
    # consumed here; no raw song_id/embedding row access remains.
    _vector_cache: dict[int, list[float] | None] = {}

    def _vector_for_file(fid: int) -> list[float] | None:
        """Return the stored embedding for ``fid`` (memoised per file handle)."""
        if fid in _vector_cache:
            return _vector_cache[fid]
        vector: list[float] | None = None
        song = db.library.resolve_song_identity(fid)
        if song is not None:
            song_vector = db.ml.get_song_vector(resolved_backbone, song)
            if song_vector is not None:
                vector = list(song_vector.vector)
        _vector_cache[fid] = vector
        return vector

    # Group file_ids by genre
    # get_tag_values_grouped_by_file returns {file_id: {genre_set}}
    file_genre_map: dict[int, set[str]] = {}
    if backbone_id:
        file_genre_map = get_tag_values_grouped_by_file(db, file_ids, "genre")

    # Invert to {genre: set[file_ids]}
    genre_to_files: dict[str, set[int]] = {}
    for fid, genres in file_genre_map.items():
        for genre in genres:
            genre_to_files.setdefault(genre, set()).add(fid)

    # Build per-genre clusters
    clusters: list[dict] = []
    for genre_label, genre_file_set in genre_to_files.items():
        genre_plays = [p for p in resolved_plays if p.get("file_id") in genre_file_set]
        if len(genre_plays) < 3:
            continue

        paired: list[tuple[TrackPlayData, list[float]]] = []
        for play in genre_plays:
            fid = play.get("file_id")
            if fid is None:
                continue
            vec = _vector_for_file(fid)
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
            },
        )

    # Add untagged cluster for files without genre
    tagged_file_ids = set().union(*genre_to_files.values()) if genre_to_files else set()
    untagged_file_ids = set(file_ids) - tagged_file_ids
    if untagged_file_ids:
        untagged_plays = [p for p in resolved_plays if p.get("file_id") in untagged_file_ids]
        if len(untagged_plays) >= 3:
            ut_paired: list[tuple[TrackPlayData, list[float]]] = []
            for play in untagged_plays:
                fid = play.get("file_id")
                if fid is None:
                    continue
                vec = _vector_for_file(fid)
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
                    },
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
        days_since = (now_ms_val - last_ms) / _MS_PER_DAY if last_ms is not None else fallback_days

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
