"""Recency-weighted taste-profile computation from caller-provided play history (Navidrome plugin/request boundary)."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, cast

import numpy as np

from nomarr.components.tagging.tag_query_comp import get_tag_values_grouped_by_file
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.song_locator_codec import SongLocatorFormatError, decode_song_locator
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.navidrome_dto import TasteProfile, TrackPlayData
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _resolve_token(db: Database, token: str) -> SongIdentity | None:
    """Resolve an opaque ``nom1`` play token to its UUID-bearing ``SongIdentity``.

    Strict codec decode followed by the public library-UUID facade, mirroring the
    Navidrome service/component precedent. Malformed tokens and unknown libraries
    are a miss (``None``); no generated integer identity is accepted or produced.
    """
    try:
        payload = decode_song_locator(token)
    except SongLocatorFormatError:
        return None
    library = db.library.get_library_by_uuid(payload.library_uuid)
    if library is None:
        return None
    identity = LibraryIdentity(
        library_uuid=library.library_uuid or payload.library_uuid,
        name=library.name,
        root_path=library.root_path,
    )
    return SongIdentity(library=identity, normalized_path=payload.path)


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

    Each play's ``file_id`` is an opaque ``nom1`` SongLocator token; it is
    resolved to a mutable
    :class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
    through the canonical codec and the authoritative ``db.library`` facade, and
    its embedding is read as a domain
    :class:`~nomarr.helpers.dataclasses.vector_dataclass.SongVector` via the
    typed ``db.ml.get_song_vector`` intent — never a raw persistence row, storage
    key, or generated id.

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

    now_val = now_ms().value
    resolved_backbone = backbone_id or "default"

    # Resolve each distinct opaque token once to its mutable SongIdentity; an
    # unresolved/malformed token is dropped before any authoritative tag/vector
    # read. Only semantic locators cross the component boundary from here.
    locator_by_token: dict[str, SongIdentity] = {}
    for play in resolved_plays:
        token = play["file_id"]
        if token is None or token in locator_by_token:
            continue
        locator = _resolve_token(db, token)
        if locator is not None:
            locator_by_token[token] = locator

    locators = list(locator_by_token.values())

    # Memoised per-locator resolution: the cold-tier stored vector is read as a
    # SongVector via db.ml. No raw song_id/embedding row access remains.
    _vector_cache: dict[SongIdentity, list[float] | None] = {}

    def _vector_for_locator(locator: SongIdentity) -> list[float] | None:
        """Return the stored embedding for ``locator`` (memoised per locator)."""
        if locator in _vector_cache:
            return _vector_cache[locator]
        vector: list[float] | None = None
        song_vector = db.ml.get_song_vector(resolved_backbone, locator)
        if song_vector is not None:
            vector = list(song_vector.vector)
        _vector_cache[locator] = vector
        return vector

    # Group locators by genre; the analytics helper is locator-keyed.
    file_genre_map: dict[SongIdentity, set[str]] = {}
    if backbone_id:
        file_genre_map = get_tag_values_grouped_by_file(db, locators, "genre")

    # Invert to {genre: set[locators]}
    genre_to_locators: dict[str, set[SongIdentity]] = {}
    for locator, genres in file_genre_map.items():
        for genre in genres:
            genre_to_locators.setdefault(genre, set()).add(locator)

    # Build per-genre clusters
    clusters: list[dict] = []
    for genre_label, genre_locators in genre_to_locators.items():
        genre_plays = [
            p
            for p in resolved_plays
            if (token := p["file_id"]) is not None and locator_by_token.get(token) in genre_locators
        ]
        if len(genre_plays) < 3:
            continue

        paired: list[tuple[TrackPlayData, list[float]]] = []
        for play in genre_plays:
            token = play["file_id"]
            if token is None:
                continue
            locator = locator_by_token.get(token)
            if locator is None:
                continue
            vec = _vector_for_locator(locator)
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

    # Add untagged cluster for locators without genre
    tagged_locators = set().union(*genre_to_locators.values()) if genre_to_locators else set()
    untagged_locators = set(locators) - tagged_locators
    if untagged_locators:
        untagged_plays = [
            p
            for p in resolved_plays
            if (token := p["file_id"]) is not None and locator_by_token.get(token) in untagged_locators
        ]
        if len(untagged_plays) >= 3:
            ut_paired: list[tuple[TrackPlayData, list[float]]] = []
            for play in untagged_plays:
                token = play["file_id"]
                if token is None:
                    continue
                locator = locator_by_token.get(token)
                if locator is None:
                    continue
                vec = _vector_for_locator(locator)
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
