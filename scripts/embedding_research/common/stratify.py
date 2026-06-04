"""Shared stratification phase logic for embedding research."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

from scripts.embedding_research import db
from scripts.embedding_research.config import OUTPUT_ROOT

ResearchConfig = dict[str, Any]

_log = logging.getLogger(__name__)
_MATRIX_CACHE_DIR = OUTPUT_ROOT / "cache" / "stratify_membership"


def _score_to_decile(score: float) -> int:
    return max(0, min(int(score * 10), 9))


def _budget_tolerance(limit_n: int, cfg: ResearchConfig) -> int:
    strat_cfg = cfg.get("stratify", {}) if isinstance(cfg.get("stratify"), dict) else {}
    small_limit = int(strat_cfg.get("budget_anchor_small_limit", 20))
    small_over = int(strat_cfg.get("budget_anchor_small_over", 10))
    large_limit = int(strat_cfg.get("budget_anchor_large_limit", 2000))
    large_over = int(strat_cfg.get("budget_anchor_large_over", 100))

    small_limit = max(1, small_limit)
    large_limit = max(small_limit + 1, large_limit)
    small_over = max(0, small_over)
    large_over = max(small_over, large_over)

    l1 = math.log1p(small_limit)
    l2 = math.log1p(large_limit)
    lx = math.log1p(limit_n)
    if l2 <= l1:
        return small_over
    b = (large_over - small_over) / (l2 - l1)
    a = small_over - (b * l1)
    return max(0, int(round(a + (b * lx))))


def _size_penalty(size_n: int, limit_n: int, tolerance_n: int, cfg: ResearchConfig) -> float:
    if limit_n <= 0:
        return 0.0
    strat_cfg = cfg.get("stratify", {}) if isinstance(cfg.get("stratify"), dict) else {}
    size_weight = float(strat_cfg.get("size_penalty_weight", 0.6))
    over_quad = float(strat_cfg.get("overbudget_quad_weight", 0.05))

    delta = abs(size_n - limit_n)
    penalty = size_weight * float(delta)
    if size_n <= limit_n:
        return penalty
    over = size_n - limit_n
    extra = max(0, over - tolerance_n)
    return penalty + (over_quad * float(extra * extra))


def _matrix_cache_key(sids_sorted: list[str], min_genre_size: int, heads_signature: list[str]) -> str:
    payload = json.dumps(
        {
            "sids": sids_sorted,
            "min_genre_size": int(min_genre_size),
            "heads": heads_signature,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:20]


def _load_or_build_membership_matrix(
    *,
    sids_sorted: list[str],
    genre_by_sid: dict[str, str],
    artist_by_sid: dict[str, str],
    min_genre_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    from scripts.embedding_research import config as _cfg
    from scripts.embedding_research.cache import flat_heads as _fh

    heads_signature = [f"{bb}:{hd}" for bb in sorted(_cfg.HEADS) for hd in sorted(_cfg.HEADS[bb])]
    cache_key = _matrix_cache_key(sids_sorted, min_genre_size, heads_signature)
    _MATRIX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = _MATRIX_CACHE_DIR / f"{cache_key}.npz"

    if npz_path.exists():
        with np.load(npz_path, allow_pickle=False) as data:
            cached_sids = data["song_ids"].astype(str)
            if cached_sids.tolist() == sids_sorted:
                _log.info("[stratify] Membership matrix cache hit: %s", npz_path.name)
                return (
                    cached_sids,
                    data["genre_bucket"].astype(str),
                    data["artist_name"].astype(str),
                    data["head_soft_deciles"].astype(np.float32),
                )

    genre_counts: dict[str, int] = {}
    for sid in sids_sorted:
        g = genre_by_sid.get(sid, "unknown")
        genre_counts[g] = genre_counts.get(g, 0) + 1

    genre_bucket = np.array(
        [
            g if genre_counts.get(g, 0) >= min_genre_size else "__other__"
            for g in (genre_by_sid.get(sid, "unknown") for sid in sids_sorted)
        ],
        dtype=str,
    )
    artist_name = np.array([artist_by_sid.get(sid, "unknown") for sid in sids_sorted], dtype=str)

    sid_to_idx = {sid: i for i, sid in enumerate(sids_sorted)}
    head_soft_deciles = np.zeros((len(sids_sorted), 10), dtype=np.float32)
    if sids_sorted:
        total_heads = sum(len(heads_cfg) for heads_cfg in _cfg.HEADS.values())
        head_idx = 0
        for backbone, heads_cfg in _cfg.HEADS.items():
            for head_name in heads_cfg:
                head_idx += 1
                _log.info(
                    "[stratify] Building head memberships %d/%d (%s/%s)",
                    head_idx,
                    total_heads,
                    backbone,
                    head_name,
                )
                acts = _fh.load_bulk(backbone, head_name, "mean", "ptc", sids_sorted)
                for sid, act in acts.items():
                    if act.size < 2:
                        continue
                    idx = sid_to_idx.get(sid)
                    if idx is None:
                        continue
                    dec = _score_to_decile(float(act[-1]))
                    head_soft_deciles[idx, dec] += 1.0

    row_sums = head_soft_deciles.sum(axis=1, keepdims=True)
    nonzero = row_sums[:, 0] > 0
    head_soft_deciles[nonzero] = head_soft_deciles[nonzero] / row_sums[nonzero]

    np.savez_compressed(
        npz_path,
        song_ids=np.array(sids_sorted, dtype=str),
        genre_bucket=genre_bucket,
        artist_name=artist_name,
        head_soft_deciles=head_soft_deciles,
    )
    _log.info("[stratify] Cached membership matrix: %s (%d songs)", npz_path.name, len(sids_sorted))
    return np.array(sids_sorted, dtype=str), genre_bucket, artist_name, head_soft_deciles


def _select_budgeted_subset(
    *,
    song_ids: np.ndarray,
    genre_bucket: np.ndarray,
    artist_name: np.ndarray,
    head_soft_deciles: np.ndarray,
    limit_n: int,
    cfg: ResearchConfig,
) -> list[str]:
    n = int(song_ids.shape[0])
    if n == 0:
        return []
    if limit_n <= 0:
        return sorted(song_ids.tolist())

    tolerance = _budget_tolerance(limit_n, cfg)
    strat_cfg = cfg.get("stratify", {}) if isinstance(cfg.get("stratify"), dict) else {}
    hard_mult = float(strat_cfg.get("hard_overbudget_multiplier", 3.0))
    hard_over = max(0, int(round(tolerance * hard_mult)))
    hard_max = min(n, limit_n + hard_over)

    w_genre = float(strat_cfg.get("weight_genre", 1.0))
    w_head = float(strat_cfg.get("weight_head", 1.0))
    w_artist = float(strat_cfg.get("weight_artist", 0.35))

    genre_counts: dict[str, int] = {}
    artist_counts: dict[str, int] = {}
    decile_counts = np.zeros(10, dtype=np.float64)

    sid_values = song_ids.tolist()
    genre_values = genre_bucket.tolist()
    artist_values = artist_name.tolist()

    remaining = set(range(n))
    selected: list[int] = []
    objectives: list[float] = []
    progress_every = max(100, hard_max // 20)  # ~5% updates for long runs

    for step in range(hard_max):
        best_idx: int | None = None
        best_gain = float("-inf")
        for idx in remaining:
            g = genre_values[idx]
            a = artist_values[idx]
            gain = (w_genre / (1.0 + genre_counts.get(g, 0))) + (w_artist / (1.0 + artist_counts.get(a, 0)))
            gain += w_head * float(np.sum(head_soft_deciles[idx] / (1.0 + decile_counts)))

            if gain > best_gain:
                best_gain = gain
                best_idx = idx
            elif gain == best_gain and best_idx is not None and sid_values[idx] < sid_values[best_idx]:
                best_idx = idx

        if best_idx is None:
            break

        remaining.remove(best_idx)
        selected.append(best_idx)

        g = genre_values[best_idx]
        a = artist_values[best_idx]
        genre_counts[g] = genre_counts.get(g, 0) + 1
        artist_counts[a] = artist_counts.get(a, 0) + 1
        decile_counts += head_soft_deciles[best_idx]

        size_n = len(selected)
        genre_arr = np.array(list(genre_counts.values()), dtype=np.float64)
        genre_dist = genre_arr / max(1.0, float(np.sum(genre_arr)))
        genre_uniform = 1.0 - (0.5 * float(np.sum(np.abs(genre_dist - (1.0 / max(1, genre_dist.size))))))

        dec_sum = float(np.sum(decile_counts))
        if dec_sum > 0:
            dec_dist = decile_counts / dec_sum
            head_uniform = 1.0 - (0.5 * float(np.sum(np.abs(dec_dist - 0.1))))
        else:
            head_uniform = 0.5

        artist_arr = np.array(list(artist_counts.values()), dtype=np.float64)
        artist_dist = artist_arr / max(1.0, float(np.sum(artist_arr)))
        artist_div = 1.0 - float(np.sum(np.square(artist_dist)))

        quality = (w_genre * genre_uniform) + (w_head * head_uniform) + (w_artist * artist_div)
        objectives.append(quality - _size_penalty(size_n, limit_n, tolerance, cfg))

        if (step + 1) % progress_every == 0 or (step + 1) == hard_max:
            _log.info(
                "[stratify] Selector progress: %d/%d candidates chosen",
                step + 1,
                hard_max,
            )

    if not selected:
        return []

    best_pos = 0
    best_obj = objectives[0]
    for i, obj in enumerate(objectives):
        if obj > best_obj:
            best_obj = obj
            best_pos = i
        elif obj == best_obj:
            cand_size = i + 1
            best_size = best_pos + 1
            if abs(cand_size - limit_n) < abs(best_size - limit_n):
                best_pos = i

    chosen = [sid_values[i] for i in selected[: best_pos + 1]]
    return sorted(chosen)


def run_stratify(con, cfg: ResearchConfig, config_hash: str) -> frozenset[str]:
    """Return a stratified corpus of song IDs for the given config.

    Results are cached in the ``stratified_corpus`` table keyed by
    ``config_hash``. On a cache hit the stored set is returned immediately.

    On a cache miss, a filesystem-cached membership matrix is built over the
    full eligible corpus and a budget-aware selector chooses a deterministic
    subset using soft group memberships.

    Args:
        con: Open DuckDB connection.
        cfg: Research config dict. The stratifier reads ``song_ids`` and
            ``limit`` when present.
        config_hash: Hex digest of the serialized config used as the cache key.

    Returns:
        Frozenset of ``song_id`` strings in the stratified corpus.
    """
    cached = db.load_stratified_sids(con, config_hash)
    if cached:
        _log.info("[stratify] Using cached stratified corpus: %d songs (config_hash=%s)", len(cached), config_hash)
        return cached

    requested_song_ids = cfg.get("song_ids")
    requested_sid_set = set(requested_song_ids) if requested_song_ids is not None else None

    songs = db.load_all_songs(con)
    sids: list[str] = []
    artist_by_sid: dict[str, str] = {}
    genre_by_sid: dict[str, str] = {}
    for song in songs:
        sid = str(song["song_id"])
        if requested_sid_set is not None and sid not in requested_sid_set:
            continue
        sids.append(sid)
        artist_by_sid[sid] = str(song.get("artist") or "unknown")
        genre_by_sid[sid] = str(song.get("genre") or "unknown")

    sids_sorted = sorted(sids)
    if not sids_sorted:
        return frozenset()

    from scripts.embedding_research.helpers.toml import load_research_config as _load_rc

    rcfg = _load_rc()
    limit_n = int(cfg.get("limit") or 0)
    min_genre_size = int(rcfg.get("stratify", {}).get("min_genre_size", 10))

    _log.info(
        "[stratify] Building/loading membership matrix from full corpus (%d songs)",
        len(sids_sorted),
    )

    song_ids_mx, genre_bucket_mx, artist_mx, head_soft_mx = _load_or_build_membership_matrix(
        sids_sorted=sids_sorted,
        genre_by_sid=genre_by_sid,
        artist_by_sid=artist_by_sid,
        min_genre_size=min_genre_size,
    )
    _log.info("[stratify] Membership matrix ready: %d songs", len(song_ids_mx))

    _log.info("[stratify] Running budgeted selector (limit=%d)", limit_n)

    chosen = _select_budgeted_subset(
        song_ids=song_ids_mx,
        genre_bucket=genre_bucket_mx,
        artist_name=artist_mx,
        head_soft_deciles=head_soft_mx,
        limit_n=limit_n,
        cfg=rcfg,
    )

    tolerance = _budget_tolerance(limit_n, rcfg) if limit_n > 0 else 0
    _log.info(
        "[stratify] Budgeted selection: %d → %d songs (limit=%d, tolerance=%d)",
        len(sids_sorted),
        len(chosen),
        limit_n,
        tolerance,
    )

    db.clear_stale_stratification(con, config_hash)
    result = frozenset(chosen)
    db.write_stratified_sids(con, config_hash, result)
    _log.info("[stratify] Wrote %d stratified song IDs (config_hash=%s)", len(result), config_hash)
    return result
