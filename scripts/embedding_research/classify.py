"""Unified head inference for flat and binned embedding-research workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
from tqdm import tqdm

from .cache import binned_ctp as _binned_ctp_cache
from .cache import binned_ctp_heads as _binned_ctp_heads_cache
from .cache import binned_ptc as _binned_ptc_cache
from .cache import flat_heads as _flat_heads_cache
from .cache.flat_vecs import load_matrix as _load_flat_matrix
from .config import BACKBONES, HEAD_VRAM_BYTES, HEADS, bootstrap_nomarr, discover_audio, patches_path, song_id
from .helpers.binning import BIN_MODES, global_dist, temporal_segment
from .helpers.binning import DIST_THRESHOLDS as DEFAULT_STD_THRESHOLDS
from .pooling import STRATEGIES

__all__ = ["run_binned", "run_flat"]

_log = logging.getLogger(__name__)

from scripts.embedding_research.strategy_binned._constants import _BIN_POOL_STRATEGIES as _BIN_POOL_FNS  # noqa: E402


def _l2_normalise_vec(v: np.ndarray) -> np.ndarray:
    """L2-normalise a single 1-D float32 vector; returns unchanged if near-zero."""
    norm = float(np.linalg.norm(v))
    return (v / norm).astype(np.float32) if norm > 1e-9 else v.astype(np.float32)


def _run_head_session(session, embed_batch: np.ndarray) -> np.ndarray:
    """Run a head ONNX session on one vector or a batch of vectors."""
    inp = embed_batch if embed_batch.ndim == 2 else embed_batch[None, :]
    out = session.run(["activations"], {"embeddings": inp.astype(np.float32)})[0]
    return np.asarray(out, dtype=np.float32)




def _classify_song(
    path: Path,
    backbone_name: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    pooled_map: dict[str, np.ndarray | None],
    done_set: set[tuple[str, str, str, str]] | None = None,
    force: bool = False,
) -> bool:
    """Compute flat PTC + CTP activations for one song and save to filesystem cache."""
    sid = song_id(path)
    if (
        not force
        and done_set is not None
        and all((sid, backbone_name, head_name, strategy_name) in done_set for strategy_name in STRATEGIES)
    ):
        return False

    sidecar = patches_path(sid, backbone_name)
    if not sidecar.exists():
        return False

    patches = np.load(str(sidecar)).astype(np.float32)
    if patches.size == 0:
        return False

    try:
        patch_acts = run_in_batches_fn(
            lambda batch: _run_head_session(head_session, batch),
            patches,
            batch_size,
        ).astype(np.float32)
    except Exception as exc:
        raise RuntimeError(f"CTP head inference failed for {path.name}/{head_name}") from exc

    wrote_any = False
    for strategy_name, pool_fn in STRATEGIES.items():
        if not force and done_set is not None and (sid, backbone_name, head_name, strategy_name) in done_set:
            continue

        pool = cast("Callable[[np.ndarray], np.ndarray]", pool_fn)
        pooled_vec = pooled_map.get(strategy_name)
        if pooled_vec is None:
            pooled_vec = pool(patches).astype(np.float32)
        else:
            pooled_vec = np.asarray(pooled_vec, dtype=np.float32)
        ptc_act = _run_head_session(head_session, pooled_vec)[0]
        ctp_act = np.asarray(pool(patch_acts), dtype=np.float32)

        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ptc", sid, ptc_act)
        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ctp", sid, ctp_act)
        wrote_any = True

    return wrote_any


def _classify_song_missing(
    path: Path,
    backbone_name: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    pooled_map: dict[str, np.ndarray | None],
    missing_strats: frozenset[str],
) -> bool:
    """Compute flat PTC + CTP activations for exactly the missing strategies."""
    if not missing_strats:
        return False

    sidecar = patches_path(song_id(path), backbone_name)
    if not sidecar.exists():
        return False

    patches = np.load(str(sidecar)).astype(np.float32)
    if patches.size == 0:
        return False

    try:
        patch_acts = run_in_batches_fn(
            lambda batch: _run_head_session(head_session, batch),
            patches,
            batch_size,
        ).astype(np.float32)
    except Exception as exc:
        raise RuntimeError(f"CTP head inference failed for {path.name}/{head_name}") from exc

    sid = song_id(path)
    wrote_any = False
    for strategy_name, pool_fn in STRATEGIES.items():
        if strategy_name not in missing_strats:
            continue
        pool = cast("Callable[[np.ndarray], np.ndarray]", pool_fn)
        pooled_vec = pooled_map.get(strategy_name)
        if pooled_vec is None:
            pooled_vec = pool(patches).astype(np.float32)
        else:
            pooled_vec = np.asarray(pooled_vec, dtype=np.float32)
        ptc_act = _run_head_session(head_session, pooled_vec)[0]
        ctp_act = np.asarray(pool(patch_acts), dtype=np.float32)
        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ptc", sid, ptc_act)
        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ctp", sid, ctp_act)
        wrote_any = True

    return wrote_any


def _process_song_head_missing(
    sid: str,
    backbone: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    patches: np.ndarray,
    missing_combos: frozenset[tuple[str, float]],
) -> tuple[int, int]:
    """Run a head on patches for exactly the missing (bin_mode, std_thresh) combos.

    Saves results directly to the filesystem cache:

    * ``binned_ctp_heads`` — per-bin mean head activations
    * ``binned_ctp`` — per-bin embedding pool vectors (one strategy × one bin)

    Returns ``(n_head_combos_saved, n_vec_combos_saved)``.
    """
    if not missing_combos:
        return 0, 0

    acts = run_in_batches_fn(
        lambda batch: _run_head_session(head_session, batch),
        patches,
        batch_size,
    ).astype(np.float32)
    if acts.size == 0:
        return 0, 0

    scores = acts[:, 1]
    score_column = scores.reshape(-1, 1).astype(np.float32)
    score_std = float(scores.std())
    if score_std < 1e-9:
        score_std = 1.0

    saved_heads = saved_vecs = 0
    for bin_mode, std_thresh in missing_combos:
        threshold = float(std_thresh) * score_std
        segments = temporal_segment(score_column, threshold, global_dist)

        bin_acts_list: list[np.ndarray] = []
        bin_weights_list: list[int] = []
        vec_rows_for_combo: list[tuple] = []

        for bin_id, seg in enumerate(segments):
            indices = seg["indices"]
            if not indices:
                continue
            outlier_count = int(seg.get("outlier_count", 0))

            # Head activations for this bin
            seg_acts = acts[indices]
            mean_act = seg_acts.mean(axis=0).astype(np.float32)
            bin_acts_list.append(mean_act)
            bin_weights_list.append(len(indices))

            # Embedding pool vecs for this bin
            seg_patches = patches[indices].astype(np.float32)
            for pool_name, pool_fn in _BIN_POOL_FNS.items():
                vec_raw = pool_fn(seg_patches)
                vec_norm = _l2_normalise_vec(vec_raw)
                vec_rows_for_combo.append((
                    sid, backbone, head_name, bin_mode, float(std_thresh),
                    int(bin_id), pool_name, vec_raw.tobytes(), vec_norm.tobytes(),
                    len(indices), outlier_count,
                ))

        if bin_acts_list:
            acts_arr = np.stack(bin_acts_list).astype(np.float32)
            wts_arr = np.array(bin_weights_list, dtype=np.int32)
            _binned_ctp_heads_cache.save(backbone, head_name, bin_mode, std_thresh, sid, acts_arr, wts_arr)
            saved_heads += 1

        if vec_rows_for_combo:
            _binned_ctp_cache.save(backbone, head_name, bin_mode, std_thresh, sid, vec_rows_for_combo)
            saved_vecs += 1

    return saved_heads, saved_vecs


def _process_song_head(
    sid: str,
    backbone: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    patches: np.ndarray,
    std_thresholds: list[float],
    force: bool,
    done_set: set[tuple[str, str, str, str, float]] | None = None,
) -> tuple[int, int]:
    """Run a head on all patches for all (bin_mode, std_thresh) combos (force path).

    Same filesystem-save behaviour as :func:`_process_song_head_missing`.
    """
    missing: frozenset[tuple[str, float]]
    if not force and done_set is not None:
        all_done = all(
            (sid, backbone, head_name, bin_mode, float(std_thresh)) in done_set
            for bin_mode in BIN_MODES
            for std_thresh in std_thresholds
        )
        if all_done:
            return 0, 0
        missing = frozenset(
            (bm, float(st))
            for bm in BIN_MODES
            for st in std_thresholds
            if (sid, backbone, head_name, bm, float(st)) not in done_set
        )
    else:
        missing = frozenset((bm, float(st)) for bm in BIN_MODES for st in std_thresholds)
    return _process_song_head_missing(sid, backbone, head_name, head_session, run_in_batches_fn, batch_size, patches, missing)


def _weighted_song_score_from_acts(acts: np.ndarray, weights: np.ndarray) -> float | None:
    """Return the weight-averaged positive-class score from per-bin acts and weights."""
    total_weight = float(weights.sum())
    if total_weight <= 0.0 or acts.ndim != 2 or acts.shape[1] < 2:
        return None
    return float(float((acts[:, 1] * weights).sum()) / total_weight)


def _safe_pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Return a defensive Pearson correlation for small or degenerate inputs."""
    if x.size < 2 or y.size < 2:
        return 0.0
    if float(x.std()) < 1e-12 or float(y.std()) < 1e-12:
        return 0.0
    corr = np.corrcoef(x, y)
    if not np.isfinite(corr[0, 1]):
        return 0.0
    return float(corr[0, 1])


def compute_metrics(
    con,
    backbones: list[str],
    bin_modes: list[str],
    std_thresholds: list[float],
    heads_filter: list[str] | None,
) -> int:
    """Compare binned PTC and CTP results and upsert divergence metrics.

    Reads head activations directly from the filesystem cache:

    * PTC head data from ``binned_ptc`` npz files (``head_{name}`` + ``weights`` arrays)
    * CTP head data from ``binned_ctp_heads`` npz files (``acts`` + ``weights`` arrays)

    Still writes computed divergence metrics to the DuckDB analysis database.
    """
    metric_rows: list[tuple] = []

    # One directory scan per cache — group by combo for O(1) lookups
    ctp_keys = _binned_ctp_heads_cache.list_done_keys()   # (sid, backbone, head, bin_mode, std_thresh)
    ptc_keys = _binned_ptc_cache.list_done_keys()          # (sid, backbone, bin_mode, std_thresh)

    ctp_sids_by_combo: dict[tuple[str, str, str, float], set[str]] = {}
    for sid_d, bb_d, hd_d, bm_d, st_d in ctp_keys:
        ctp_sids_by_combo.setdefault((bb_d, hd_d, bm_d, st_d), set()).add(sid_d)

    ptc_sids_by_combo: dict[tuple[str, str, float], set[str]] = {}
    for sid_d, bb_d, bm_d, st_d in ptc_keys:
        ptc_sids_by_combo.setdefault((bb_d, bm_d, st_d), set()).add(sid_d)

    for backbone in backbones:
        head_map = HEADS.get(backbone, {})
        head_names = [head for head in head_map if heads_filter is None or head in heads_filter]
        for head in head_names:
            for bin_mode in bin_modes:
                for std_thresh in std_thresholds:
                    ctp_sids = ctp_sids_by_combo.get((backbone, head, bin_mode, std_thresh), set())
                    ptc_sids = ptc_sids_by_combo.get((backbone, bin_mode, std_thresh), set())
                    shared_song_ids = sorted(ctp_sids & ptc_sids)
                    if not shared_song_ids:
                        _log.info(
                            "[%s/%s/%s/t=%.2f] no overlap between PTC and CTP — skip",
                            backbone, head, bin_mode, std_thresh,
                        )
                        continue

                    ptc_song_score: dict[str, float] = {}
                    ctp_song_score: dict[str, float] = {}
                    ctp_bin_counts: list[int] = []
                    head_key = f"head_{head}"

                    for sid in shared_song_ids:
                        # PTC: load from binned_ptc npz and extract head activations
                        ptc_path = _binned_ptc_cache.cache_path(backbone, bin_mode, std_thresh, sid)
                        if ptc_path.exists():
                            try:
                                ptc_data = np.load(str(ptc_path))
                                if head_key in ptc_data.files:
                                    ptc_acts = ptc_data[head_key]
                                    ptc_wts = ptc_data["weights"]
                                    ptc_data.close()
                                    score = _weighted_song_score_from_acts(ptc_acts, ptc_wts)
                                    if score is not None:
                                        ptc_song_score[sid] = score
                                else:
                                    ptc_data.close()
                            except (EOFError, OSError, ValueError, KeyError):
                                pass

                        # CTP: load from binned_ctp_heads npz
                        ctp_result = _binned_ctp_heads_cache.load(backbone, head, bin_mode, std_thresh, sid)
                        if ctp_result is not None:
                            ctp_acts, ctp_wts = ctp_result
                            score = _weighted_song_score_from_acts(ctp_acts, ctp_wts)
                            if score is not None:
                                ctp_song_score[sid] = score
                            ctp_bin_counts.append(len(ctp_wts))

                    shared_scored = sorted(set(ptc_song_score) & set(ctp_song_score))
                    if not shared_scored:
                        _log.info(
                            "[%s/%s/%s/t=%.2f] no overlap between PTC and CTP — skip",
                            backbone, head, bin_mode, std_thresh,
                        )
                        continue

                    ptc_vec = np.array([ptc_song_score[sid] for sid in shared_scored], dtype=np.float64)
                    ctp_vec = np.array([ctp_song_score[sid] for sid in shared_scored], dtype=np.float64)
                    divergence_mean = float(np.mean(np.abs(ptc_vec - ctp_vec)))
                    bin_count_var = (
                        float(np.var(np.array(ctp_bin_counts, dtype=np.float64))) if len(ctp_bin_counts) >= 2 else 0.0
                    )
                    sim_align_corr = _safe_pearson(ptc_vec, ctp_vec)

                    metric_rows.append((
                        backbone,
                        bin_mode,
                        float(std_thresh),
                        head,
                        divergence_mean,
                        bin_count_var,
                        sim_align_corr,
                    ))

    if metric_rows:
        con.executemany(
            "INSERT INTO binned_ptc_ctp_metrics "
            "(backbone, bin_mode, std_thresh, head, divergence_mean, bin_count_var, sim_align_corr) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (backbone, bin_mode, std_thresh, head) DO UPDATE SET "
            "divergence_mean=excluded.divergence_mean, "
            "bin_count_var=excluded.bin_count_var, "
            "sim_align_corr=excluded.sim_align_corr",
            metric_rows,
        )
    return len(metric_rows)


def run_flat(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    device: str = "cpu",
    head_sessions: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Run flat pooled-vector head inference using one bulk cache query.

    If *head_sessions* is provided (``{backbone: {head_name: session}}``) those
    sessions are used directly and ``create_session`` is not called.
    """
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    _all_paths = discover_audio()
    audio_paths = [p for p in _all_paths if song_id(p) in song_ids] if song_ids is not None else _all_paths
    backbone_names = backbones or list(BACKBONES)
    all_strategies = frozenset(STRATEGIES)

    # Build (sid, backbone, head) -> set[done strategies] from one DB query
    if not force:
        fully_done_flat = _flat_heads_cache.list_done_keys()   # (song_id, backbone, head_name, strategy)
        done_strats_by_key: dict[tuple[str, str, str], set[str]] = {}
        for sid_d, bb_d, head_d, strat_d in fully_done_flat:
            done_strats_by_key.setdefault((sid_d, bb_d, head_d), set()).add(strat_d)
    else:
        done_strats_by_key = {}

    for backbone_name in backbone_names:
        head_map = {
            head: model for head, model in HEADS.get(backbone_name, {}).items() if heads is None or head in heads
        }
        if not head_map:
            _log.info("[%s] No heads configured — skipping", backbone_name)
            continue

        _log.info("[%s] Pre-loading pooled vectors from DB ...", backbone_name)
        strat_to_pooled: dict[str, dict[str, np.ndarray]] = {}
        for strategy_name in STRATEGIES:
            vecs, sids, _artists, _albums, _genres = _load_flat_matrix(backbone_name, strategy_name, con)
            strat_to_pooled[strategy_name] = dict(zip(sids, vecs, strict=False)) if sids else {}
        loaded_count = max((len(song_map) for song_map in strat_to_pooled.values()), default=0)
        _log.info("[%s] Loaded %d pooled vecs across strategies", backbone_name, loaded_count)

        for head_name, head_model_path in head_map.items():
            try:
                if head_sessions is not None:
                    head_session = head_sessions.get(backbone_name, {}).get(head_name)
                    if head_session is None:
                        _log.error("[%s/%s] No cached session available — skipping", backbone_name, head_name)
                        continue
                else:
                    head_session = create_session(
                        head_model_path,
                        device=device,
                        vram_limit_bytes=HEAD_VRAM_BYTES,
                    )
            except Exception as exc:
                _log.error("[%s/%s] Failed to load head: %s", backbone_name, head_name, exc)
                continue

            # Work list: (path, frozenset_of_missing_strategies)
            work_flat: list[tuple[Path, frozenset[str]]] = []
            for p in audio_paths:
                sid = song_id(p)
                done_strats = done_strats_by_key.get((sid, backbone_name, head_name), set())
                missing = all_strategies - done_strats
                if missing:
                    work_flat.append((p, missing))
            _log.info(
                "[%s/%s] %d songs pending (%d already complete)",
                backbone_name,
                head_name,
                len(work_flat),
                len(audio_paths) - len(work_flat),
            )

            n_done = skipped = errors = 0
            started = perf_counter()
            pbar = tqdm(work_flat, desc=f"  [{backbone_name}/{head_name}]", unit="song")
            for path, missing_strats in pbar:
                sid = song_id(path)
                pooled_map = {strategy_name: strat_to_pooled[strategy_name].get(sid) for strategy_name in STRATEGIES}
                try:
                    worked = _classify_song_missing(
                        path,
                        backbone_name,
                        head_name,
                        head_session,
                        _run_in_batches,
                        _BACKBONE_BATCH_SIZE,
                        pooled_map,
                        missing_strats,
                    )
                    if worked:
                        n_done += 1
                    else:
                        skipped += 1
                    pbar.set_postfix(done=n_done, skip=skipped, err=errors)
                except Exception as exc:
                    errors += 1
                    pbar.set_postfix(done=n_done, skip=skipped, err=errors)
                    _log.error("%s: %s", path.name, exc)

            elapsed = perf_counter() - started
            _log.info(
                "[%s/%s] done=%d skip=%d err=%d  %.0fs", backbone_name, head_name, n_done, skipped, errors, elapsed
            )


def run_binned(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    device: str = "cpu",
    thresholds_by_backbone_mode: dict[tuple[str, str], list[float]] | None = None,
    head_sessions: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Run classify-then-pool binned head inference using one bulk cache query.

    If *head_sessions* is provided (``{backbone: {head_name: session}}``) those
    sessions are used directly and ``create_session`` is not called.
    """
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    _all_paths = discover_audio()
    audio_paths = [p for p in _all_paths if song_id(p) in song_ids] if song_ids is not None else _all_paths
    backbone_names = backbones or list(BACKBONES)
    if thresholds_by_backbone_mode:
        all_combos_binned: frozenset[tuple[str, float]] = frozenset(
            (bm, st) for (_, bm), thresholds in thresholds_by_backbone_mode.items() for st in thresholds
        )
    else:
        all_combos_binned = frozenset((bm, float(st)) for bm in BIN_MODES for st in DEFAULT_STD_THRESHOLDS)

    # Build (sid, backbone, head) -> set[done (bin_mode, std_thresh)] from filesystem cache
    if not force:
        ctp_heads_done = _binned_ctp_heads_cache.list_done_keys()  # (sid, backbone, head, bin_mode, std_thresh)
        done_combos_by_key: dict[tuple[str, str, str], set[tuple[str, float]]] = {}
        for sid_d, bb_d, head_d, bm_d, st_d in ctp_heads_done:
            done_combos_by_key.setdefault((sid_d, bb_d, head_d), set()).add((bm_d, st_d))
    else:
        done_combos_by_key = {}

    for backbone_name in backbone_names:
        head_map = {
            head: model for head, model in HEADS.get(backbone_name, {}).items() if heads is None or head in heads
        }
        if not head_map:
            _log.info("[%s] No heads configured — skipping", backbone_name)
            continue

        # Load all head sessions upfront so sidecar is loaded once per song across all heads
        loaded_head_sessions: dict[str, object] = {}
        for head_name, head_model_path in head_map.items():
            if head_sessions is not None:
                session = head_sessions.get(backbone_name, {}).get(head_name)
                if session is None:
                    _log.error("[%s/%s] No cached session available — skipping", backbone_name, head_name)
                    continue
                loaded_head_sessions[head_name] = session
            else:
                try:
                    loaded_head_sessions[head_name] = create_session(
                        head_model_path,
                        device=device,
                        vram_limit_bytes=HEAD_VRAM_BYTES,
                    )
                except Exception as exc:
                    _log.error("[%s/%s] Failed to load head: %s", backbone_name, head_name, exc)

        if not loaded_head_sessions:
            continue

        # Build work dict: song_path → {head_name: frozenset[missing (bin_mode, std_thresh)]}
        # Only include entries where at least one combo is missing.
        work: dict[Path, dict[str, frozenset[tuple[str, float]]]] = {}
        for p in audio_paths:
            sid = song_id(p)
            heads_missing: dict[str, frozenset[tuple[str, float]]] = {}
            for head_name in loaded_head_sessions:
                done_c = done_combos_by_key.get((sid, backbone_name, head_name), set())
                missing = all_combos_binned - done_c if not force else all_combos_binned
                if missing:
                    heads_missing[head_name] = missing
            if heads_missing:
                work[p] = heads_missing

        total_songs = len(audio_paths)
        pending_songs = len(work)
        _log.info(
            "[%s] %d songs pending (%d already complete across all heads)",
            backbone_name,
            pending_songs,
            total_songs - pending_songs,
        )

        done = skipped = errors = 0
        started = perf_counter()
        pbar = tqdm(work.items(), desc=f"[{backbone_name}] binned-classify", unit="song", total=pending_songs)
        for path, heads_missing in pbar:
            sid = song_id(path)
            sidecar = patches_path(sid, backbone_name)
            if not sidecar.exists():
                skipped += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
                continue

            try:
                patches = np.load(str(sidecar)).astype(np.float32)
                total_saved_heads = total_saved_vecs = 0
                for head_name, missing_combos in heads_missing.items():
                    head_session = loaded_head_sessions[head_name]
                    n_heads, n_vecs = _process_song_head_missing(
                        sid,
                        backbone_name,
                        head_name,
                        head_session,
                        _run_in_batches,
                        _BACKBONE_BATCH_SIZE,
                        patches,
                        missing_combos,
                    )
                    total_saved_heads += n_heads
                    total_saved_vecs += n_vecs
                if total_saved_heads > 0 or total_saved_vecs > 0:
                    done += 1
                else:
                    skipped += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
            except Exception as exc:
                errors += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
                _log.error("%s: %s", path.name, exc)

        elapsed = perf_counter() - started
        _log.info(
            "[%s] done=%d skip=%d err=%d  %.0fs",
            backbone_name,
            done,
            skipped,
            errors,
            elapsed,
        )

    upserted = compute_metrics(
        con,
        backbones=backbone_names,
        bin_modes=BIN_MODES,
        std_thresholds=sorted({st for _, st in all_combos_binned}),
        heads_filter=heads,
    )
    _log.info("binned_ptc_ctp_metrics rows upserted: %d", upserted)
