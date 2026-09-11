"""Personal playlist builders from taste profiles and play history.

Each public function builds one playlist type via ANN search against the cold
vector collection. Search results arrive as typed
:class:`~nomarr.helpers.dataclasses.vector_dataclass.VectorMatch` values carrying a
UUID-bearing :class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
locator. Builders emit the opaque ``nom1`` SongLocator token for each selected
track (never a generated integer ``songs.id``/``file_id``); nd_id resolution is the
interface layer's responsibility.
"""

from __future__ import annotations

import logging
import math
import random
from typing import TYPE_CHECKING

import numpy as np

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.navidrome_dto import (
    NavidromePersonalPlaylistContext,
    NavidromePersonalPlaylistEntry,
)
from nomarr.helpers.song_locator_codec import SongLocatorFormatError, decode_song_locator, encode_song_locator
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.vector_dataclass import VectorMatch
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_GENRE_MIN_SONGS: int = 100
_MAX_GENRE_PLAYLISTS_CAP: int = 25
_MS_PER_DAY: float = 86_400_000.0


def _resolve_token(db: Database, token: str) -> SongIdentity | None:
    """Resolve an opaque locator token to its UUID-bearing ``SongIdentity``."""
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


def _match_to_token(db: Database, match: VectorMatch) -> str | None:
    """Validate an ANN match's locator and return its opaque token, else ``None``."""
    if db.library.get_song(match.song) is None:
        return None
    return encode_song_locator(match.song)


def _tag_values_for_locators(
    db: Database,
    locators: Sequence[SongIdentity],
    name: str,
) -> dict[SongIdentity, set[str]]:
    """Batch-read one tag's values per locator through the authoritative facade."""
    if not locators:
        return {}
    assignments = db.library.list_song_tags_for_songs(list(locators))
    return {
        locator: {str(assignment.value) for assignment in assigns if assignment.name == name}
        for locator, assigns in assignments.items()
    }


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
    """Run ANN search across every taste cluster and combine results deduplicated."""
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
    """Build a Familiar playlist: ANN search biased toward played tracks."""
    played = set(ctx["played_file_ids"])
    if not played:
        return []

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=5)
    if raw_results is None:
        return []

    file_ids: list[str] = []
    for match in raw_results:
        if len(file_ids) >= ctx["max_songs"]:
            break
        token = _match_to_token(db, match)
        if token is not None and token in played:
            file_ids.append(token)

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
    played = set(ctx["played_file_ids"])

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=2)
    if raw_results is None:
        return []

    file_ids: list[str] = []
    for match in raw_results:
        if len(file_ids) >= ctx["max_songs"]:
            break
        token = _match_to_token(db, match)
        if token is not None and token not in played:
            file_ids.append(token)

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
    """Build a Hidden Gems playlist: ANN search excluding known-artist tracks."""
    played_locators = [
        loc for loc in (_resolve_token(db, token) for token in ctx["played_file_ids"]) if loc is not None
    ]
    known_artists: set[str] = set()
    for values in _tag_values_for_locators(db, played_locators, "artist").values():
        known_artists |= values
    if not known_artists:
        logger.debug("[navidrome] No known artists for hidden gems, falling back to discovery-style")

    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=3)
    if raw_results is None:
        return []

    candidates: list[tuple[VectorMatch, str]] = []
    for match in raw_results:
        token = _match_to_token(db, match)
        if token is not None:
            candidates.append((match, token))

    if known_artists:
        candidate_artists = _tag_values_for_locators(db, [match.song for match, _ in candidates], "artist")
        candidates = [
            (match, token)
            for match, token in candidates
            if not (candidate_artists.get(match.song, set()) & known_artists)
        ]

    file_ids = [token for _, token in candidates][: ctx["max_songs"]]

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
    """Build a diversified playlist via ANN search with stride sampling."""
    raw_results = _search_all_clusters(db, ctx, fetch_multiplier=3)
    if raw_results is None:
        return []

    adapted_file_ids: list[str] = []
    for match in raw_results:
        token = _match_to_token(db, match)
        if token is not None:
            adapted_file_ids.append(token)

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
    """Build per-genre playlists using per-genre recency-weighted centroids."""
    played_tracks = ctx["played_tracks"]
    if not played_tracks:
        return []

    played_file_ids = ctx["played_file_ids"]

    counts = db.ml.embedding_counts(ctx["backbone_id"])
    if counts.cold_count == 0:
        return []

    # Resolve each opaque played token to its authoritative SongIdentity and read
    # the cold-tier stored vector via db.ml. No raw song_id / embedding row access.
    token_to_song: dict[str, SongIdentity] = {}
    vector_map: dict[str, list[float]] = {}
    for token in played_file_ids:
        if token in vector_map:
            continue
        song = _resolve_token(db, token)
        if song is None:
            continue
        song_vector = db.ml.get_song_vector(ctx["backbone_id"], song)
        if song_vector is not None:
            token_to_song[token] = song
            vector_map[token] = list(song_vector.vector)

    if not vector_map:
        return []

    file_genres = _tag_values_for_locators(db, list(token_to_song.values()), "genre")

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
        song = token_to_song[pid]

        last_ms = play["last_played"]
        days_since = (now_ms_val - last_ms) / _MS_PER_DAY if last_ms is not None else fallback_days
        weight = math.log(1 + play["playcount"]) * math.exp(-decay_lambda * days_since)

        for genre in file_genres.get(song, set()):
            genre_data.setdefault(genre, []).append((weight, vec))

    if not genre_data:
        logger.debug("[navidrome] No genre affinities found for user; skipping genre playlists")
        return []

    effective_max = min(ctx["max_genre_playlists"], _MAX_GENRE_PLAYLISTS_CAP)
    genre_affinity = {g: sum(w for w, _ in wv) for g, wv in genre_data.items()}
    top_genres = sorted(genre_affinity, key=lambda g: genre_affinity[g], reverse=True)[:effective_max]

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

        file_ids: list[str] = []
        for match in raw_results:
            if len(file_ids) >= ctx["max_songs"]:
                break
            match_token = _match_to_token(db, match)
            if match_token is not None:
                file_ids.append(match_token)

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

    Args:
        results: Mapping from cluster key to list of result dicts (each
            containing a ``"file_id"`` or ``"id"`` key carrying an opaque token).
        weights: Mapping from cluster key to relative weight.
        target_size: Maximum number of items to return.

    Returns:
        Flat list of opaque locator-token strings interleaved from each cluster.

    """
    if target_size <= 0:
        return []
    if not results or not weights:
        return []

    total_weight = sum(weights.values())
    if total_weight <= 0:
        even_keys = sorted(results)
        if not even_keys:
            return []
        base = target_size // len(even_keys)
        remainder = target_size % len(even_keys)
        quotas = {k: base + (1 if i < remainder else 0) for i, k in enumerate(even_keys)}
    else:
        exact_quotas = {key: target_size * weights.get(key, 0) / total_weight for key in results}
        quotas = {key: int(exact) for key, exact in exact_quotas.items()}
        allocated = sum(quotas.values())
        remaining = target_size - allocated
        if remaining > 0:
            keys_by_frac = sorted(
                quotas,
                key=lambda k: exact_quotas[k] - int(exact_quotas[k]),
                reverse=True,
            )
            for i in range(remaining):
                quotas[keys_by_frac[i]] += 1

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
