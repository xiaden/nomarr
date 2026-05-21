"""Unified head inference for flat and binned embedding-research workflows."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import cast

import numpy as np
from tqdm import tqdm

from .config import BACKBONES, HEAD_VRAM_BYTES, HEADS, bootstrap_nomarr, discover_audio, patches_path, song_id
from .db import load_pooled_matrix, query_binned_classify_done, query_classify_done, upsert_head
from .pooling import STRATEGIES
from .helpers.binning import BIN_MODES, global_dist, temporal_segment
from .helpers.binning import STD_THRESHOLDS as DEFAULT_STD_THRESHOLDS

__all__ = ["run_binned", "run_flat"]

_log = logging.getLogger(__name__)

_UPSERT_SQL = (
    "INSERT INTO binned_classify_ctp "
    "(song_id, backbone, head, bin_mode, std_thresh, bin_id, act, weight) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (song_id, backbone, head, bin_mode, std_thresh, bin_id) "
    "DO NOTHING"
)

# CTP-derived embedding pools: same segment indices from score-stream binning,
# but applied to the raw embedding patches to produce per-segment pool vectors.
_UPSERT_CTP_VECS_SQL = (
    "INSERT INTO binned_ctp_vecs "
    "(song_id, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy, "
    " vec_raw, vec_norm, weight, outlier_count) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
    "ON CONFLICT (song_id, backbone, head, bin_mode, std_thresh, bin_id, pool_strategy) "
    "DO NOTHING"
)

# Pool functions applied to per-segment embedding patches (shape [n, d]).
_BIN_POOL_FNS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "mean": lambda x: x.mean(axis=0).astype(np.float32),
    "median": lambda x: np.median(x, axis=0).astype(np.float32),
    "max": lambda x: x.max(axis=0).astype(np.float32),
    "min": lambda x: x.min(axis=0).astype(np.float32),
}


def _l2_normalise_vec(v: np.ndarray) -> np.ndarray:
    """L2-normalise a single 1-D float32 vector; returns unchanged if near-zero."""
    norm = float(np.linalg.norm(v))
    return (v / norm).astype(np.float32) if norm > 1e-9 else v.astype(np.float32)


def _run_head_session(session, embed_batch: np.ndarray) -> np.ndarray:
    """Run a head ONNX session on one vector or a batch of vectors."""
    inp = embed_batch if embed_batch.ndim == 2 else embed_batch[None, :]
    out = session.run(["activations"], {"embeddings": inp.astype(np.float32)})[0]
    return np.asarray(out, dtype=np.float32)


def _build_flat_done_set(done_rows: set[tuple[str, str, str, str, str]]) -> set[tuple[str, str, str, str]]:
    """Collapse pathway-level cache rows into fully-complete strategy tuples."""
    pathways_by_key: defaultdict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for song_key in done_rows:
        sid, backbone, head, strategy, pathway = song_key
        pathways_by_key[(sid, backbone, head, strategy)].add(pathway)
    return {key for key, pathways in pathways_by_key.items() if {"ptc", "ctp"}.issubset(pathways)}


def _build_binned_done_set(
    done_rows: set[tuple[str, str, str, str, float, int]],
) -> set[tuple[str, str, str, str, float]]:
    """Collapse per-bin cache rows into config-level song tuples."""
    return {
        (sid, backbone, head, bin_mode, float(std_thresh))
        for sid, backbone, head, bin_mode, std_thresh, _bin_id in done_rows
    }


def _classify_song(
    path: Path,
    backbone_name: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    con,
    pooled_map: dict[str, np.ndarray | None],
    done_set: set[tuple[str, str, str, str]] | None = None,
    force: bool = False,
) -> bool:
    """Compute flat PTC + CTP activations for one song and upsert results."""
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

        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ptc", ptc_act.tolist())
        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ctp", ctp_act.tolist())
        wrote_any = True

    return wrote_any


def _classify_song_missing(
    path: Path,
    backbone_name: str,
    head_name: str,
    head_session,
    run_in_batches_fn,
    batch_size: int,
    con,
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
        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ptc", ptc_act.tolist())
        upsert_head(con, sid, backbone_name, head_name, strategy_name, "ctp", ctp_act.tolist())
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
) -> tuple[list[tuple], list[tuple]]:
    """Run a head on patches for exactly the missing (bin_mode, std_thresh) combos.

    For each CTP segment (boundaries driven by score-stream std-binning) this
    function produces **two** kinds of output rows:

    score_rows  (``binned_classify_ctp``)
        The mean head-activation vector over the score-stream segment.

    vec_rows  (``binned_ctp_vecs``)
        The embedding patches at those *same* indices pooled four ways
        (mean / median / max / min).  These are the CTP-derived embedding
        pools that can be compared to PTC-derived pools in the analysis phase.
    """
    if not missing_combos:
        return [], []

    acts = run_in_batches_fn(
        lambda batch: _run_head_session(head_session, batch),
        patches,
        batch_size,
    ).astype(np.float32)
    if acts.size == 0:
        return [], []

    scores = acts[:, 1]
    score_column = scores.reshape(-1, 1).astype(np.float32)
    score_std = float(scores.std())
    if score_std < 1e-9:
        score_std = 1.0

    score_rows: list[tuple] = []
    vec_rows: list[tuple] = []
    for bin_mode, std_thresh in missing_combos:
        threshold = float(std_thresh) * score_std
        segments = temporal_segment(score_column, threshold, global_dist)
        for bin_id, seg in enumerate(segments):
            indices = seg["indices"]
            if not indices:
                continue
            outlier_count = int(seg.get("outlier_count", 0))

            # CTP score rows: mean head activation per segment
            seg_acts = acts[indices]
            mean_act = seg_acts.mean(axis=0).astype(np.float32)
            score_rows.append(
                (
                    sid,
                    backbone,
                    head_name,
                    bin_mode,
                    float(std_thresh),
                    int(bin_id),
                    mean_act.tobytes(),
                    len(indices),
                )
            )

            # CTP embedding vec rows: pool embedding patches at the same indices
            seg_patches = patches[indices].astype(np.float32)
            for pool_name, pool_fn in _BIN_POOL_FNS.items():
                vec_raw = pool_fn(seg_patches)
                vec_norm = _l2_normalise_vec(vec_raw)
                vec_rows.append(
                    (
                        sid,
                        backbone,
                        head_name,
                        bin_mode,
                        float(std_thresh),
                        int(bin_id),
                        pool_name,
                        vec_raw.tobytes(),
                        vec_norm.tobytes(),
                        len(indices),
                        outlier_count,
                    )
                )
    return score_rows, vec_rows


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
) -> tuple[list[tuple], list[tuple]]:
    """Run a head on all patches, segment the score sequence, and return CTP rows.

    Returns (score_rows, vec_rows) — see ``_process_song_head_missing`` for details.
    """
    if not force and done_set is not None:
        all_done = all(
            (sid, backbone, head_name, bin_mode, float(std_thresh)) in done_set
            for bin_mode in BIN_MODES
            for std_thresh in std_thresholds
        )
        if all_done:
            return [], []

    acts = run_in_batches_fn(
        lambda batch: _run_head_session(head_session, batch),
        patches,
        batch_size,
    ).astype(np.float32)
    if acts.size == 0:
        return [], []

    scores = acts[:, 1]
    score_column = scores.reshape(-1, 1).astype(np.float32)
    score_std = float(scores.std())
    if score_std < 1e-9:
        score_std = 1.0

    score_rows: list[tuple] = []
    vec_rows: list[tuple] = []
    for bin_mode in BIN_MODES:
        for std_thresh in std_thresholds:
            if (
                not force
                and done_set is not None
                and (sid, backbone, head_name, bin_mode, float(std_thresh)) in done_set
            ):
                continue
            threshold = float(std_thresh) * score_std
            segments = temporal_segment(score_column, threshold, global_dist)
            for bin_id, seg in enumerate(segments):
                indices = seg["indices"]
                if not indices:
                    continue
                outlier_count = int(seg.get("outlier_count", 0))

                seg_acts = acts[indices]
                mean_act = seg_acts.mean(axis=0).astype(np.float32)
                score_rows.append(
                    (
                        sid,
                        backbone,
                        head_name,
                        bin_mode,
                        float(std_thresh),
                        int(bin_id),
                        mean_act.tobytes(),
                        len(indices),
                    )
                )

                seg_patches = patches[indices].astype(np.float32)
                for pool_name, pool_fn in _BIN_POOL_FNS.items():
                    vec_raw = pool_fn(seg_patches)
                    vec_norm = _l2_normalise_vec(vec_raw)
                    vec_rows.append(
                        (
                            sid,
                            backbone,
                            head_name,
                            bin_mode,
                            float(std_thresh),
                            int(bin_id),
                            pool_name,
                            vec_raw.tobytes(),
                            vec_norm.tobytes(),
                            len(indices),
                            outlier_count,
                        )
                    )
    return score_rows, vec_rows


def _weighted_song_score(rows: list[tuple]) -> float | None:
    """Return the weight-averaged positive-class score from per-bin rows."""
    if not rows:
        return None

    total_weight = 0.0
    total_value = 0.0
    for act_blob, weight in rows:
        arr = np.frombuffer(act_blob, np.float32)
        if arr.size < 2:
            continue
        total_value += float(arr[1]) * float(weight)
        total_weight += float(weight)

    if total_weight <= 0.0:
        return None
    return total_value / total_weight


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
    """Compare binned PTC and CTP results and upsert divergence metrics."""
    metric_rows: list[tuple] = []

    for backbone in backbones:
        head_map = HEADS.get(backbone, {})
        head_names = [head for head in head_map if heads_filter is None or head in heads_filter]
        for head in head_names:
            for bin_mode in bin_modes:
                for std_thresh in std_thresholds:
                    ptc_raw = con.execute(
                        "SELECT song_id, act, weight FROM binned_head_results "
                        "WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?",
                        [backbone, head, bin_mode, float(std_thresh)],
                    ).fetchall()
                    ptc_by_song: defaultdict[str, list[tuple]] = defaultdict(list)
                    for sid, act_blob, weight in ptc_raw:
                        ptc_by_song[sid].append((act_blob, weight))
                    ptc_song_score: dict[str, float] = {}
                    for sid, rows in ptc_by_song.items():
                        score = _weighted_song_score(rows)
                        if score is not None:
                            ptc_song_score[sid] = score

                    ctp_raw = con.execute(
                        "SELECT song_id, act, weight FROM binned_classify_ctp "
                        "WHERE backbone=? AND head=? AND bin_mode=? AND std_thresh=?",
                        [backbone, head, bin_mode, float(std_thresh)],
                    ).fetchall()
                    ctp_by_song: defaultdict[str, list[tuple]] = defaultdict(list)
                    for sid, act_blob, weight in ctp_raw:
                        ctp_by_song[sid].append((act_blob, weight))
                    ctp_song_score: dict[str, float] = {}
                    ctp_bin_counts: list[int] = []
                    for sid, rows in ctp_by_song.items():
                        score = _weighted_song_score(rows)
                        if score is not None:
                            ctp_song_score[sid] = score
                        ctp_bin_counts.append(len(rows))

                    shared_song_ids = sorted(set(ptc_song_score) & set(ctp_song_score))
                    if not shared_song_ids:
                        _log.info(
                            "[%s/%s/%s/t=%.2f] no overlap between PTC and CTP — skip",
                            backbone, head, bin_mode, std_thresh,
                        )
                        continue

                    ptc_vec = np.array([ptc_song_score[sid] for sid in shared_song_ids], dtype=np.float64)
                    ctp_vec = np.array([ctp_song_score[sid] for sid in shared_song_ids], dtype=np.float64)
                    divergence_mean = float(np.mean(np.abs(ptc_vec - ctp_vec)))
                    bin_count_var = (
                        float(np.var(np.array(ctp_bin_counts, dtype=np.float64))) if len(ctp_bin_counts) >= 2 else 0.0
                    )
                    sim_align_corr = _safe_pearson(ptc_vec, ctp_vec)

                    metric_rows.append(
                        (
                            backbone,
                            bin_mode,
                            float(std_thresh),
                            head,
                            divergence_mean,
                            bin_count_var,
                            sim_align_corr,
                        )
                    )

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
) -> None:
    """Run flat pooled-vector head inference using one bulk cache query."""
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    _all_paths = discover_audio()
    audio_paths = (
        [p for p in _all_paths if song_id(p) in song_ids]
        if song_ids is not None
        else _all_paths
    )
    backbone_names = backbones or list(BACKBONES)
    all_strategies = frozenset(STRATEGIES)

    # Build (sid, backbone, head) -> set[done strategies] from one DB query
    if not force:
        flat_done_raw = query_classify_done(con)
        fully_done_flat = _build_flat_done_set(flat_done_raw)
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
            vecs, sids, _artists, _albums, _genres = load_pooled_matrix(con, backbone_name, strategy_name)
            strat_to_pooled[strategy_name] = dict(zip(sids, vecs, strict=False)) if sids else {}
        loaded_count = max((len(song_map) for song_map in strat_to_pooled.values()), default=0)
        _log.info("[%s] Loaded %d pooled vecs across strategies", backbone_name, loaded_count)

        for head_name, head_model_path in head_map.items():
            _log.info("[%s/%s] Loading head session ...", backbone_name, head_name)
            try:
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
            _log.info("[%s/%s] %d songs pending (%d already complete)", backbone_name, head_name, len(work_flat), len(audio_paths) - len(work_flat))

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
                        con,
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
                    tqdm.write(f"  [ERROR] {path.name}: {exc}")

            elapsed = perf_counter() - started
            _log.info("[%s/%s] done=%d skip=%d err=%d  %.0fs", backbone_name, head_name, n_done, skipped, errors, elapsed)


def run_binned(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    device: str = "cpu",
) -> None:
    """Run classify-then-pool binned head inference using one bulk cache query."""
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    _all_paths = discover_audio()
    audio_paths = (
        [p for p in _all_paths if song_id(p) in song_ids]
        if song_ids is not None
        else _all_paths
    )
    backbone_names = backbones or list(BACKBONES)
    thresholds = [float(threshold) for threshold in DEFAULT_STD_THRESHOLDS]
    all_combos_binned: frozenset[tuple[str, float]] = frozenset(
        (bm, st) for bm in BIN_MODES for st in thresholds
    )

    # Build (sid, backbone, head) -> set[done (bin_mode, std_thresh)] from one DB query
    if not force:
        binned_done_raw = query_binned_classify_done(con)
        done_combos_by_key: dict[tuple[str, str, str], set[tuple[str, float]]] = {}
        for sid_d, bb_d, head_d, bm_d, st_d, _bin_id in binned_done_raw:
            key = (sid_d, bb_d, head_d)
            if key not in done_combos_by_key:
                done_combos_by_key[key] = set()
            done_combos_by_key[key].add((bm_d, float(st_d)))
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
        head_sessions: dict[str, object] = {}
        for head_name, head_model_path in head_map.items():
            _log.info("[%s/%s] Loading head session ...", backbone_name, head_name)
            try:
                head_sessions[head_name] = create_session(
                    head_model_path,
                    device=device,
                    vram_limit_bytes=HEAD_VRAM_BYTES,
                )
            except Exception as exc:
                _log.error("[%s/%s] Failed to load head: %s", backbone_name, head_name, exc)

        if not head_sessions:
            continue

        # Build work dict: song_path → {head_name: frozenset[missing (bin_mode, std_thresh)]}
        # Only include entries where at least one combo is missing.
        work: dict[Path, dict[str, frozenset[tuple[str, float]]]] = {}
        for p in audio_paths:
            sid = song_id(p)
            heads_missing: dict[str, frozenset[tuple[str, float]]] = {}
            for head_name in head_sessions:
                done_c = done_combos_by_key.get((sid, backbone_name, head_name), set())
                missing = all_combos_binned - done_c if not force else all_combos_binned
                if missing:
                    heads_missing[head_name] = missing
            if heads_missing:
                work[p] = heads_missing

        total_songs = len(audio_paths)
        pending_songs = len(work)
        _log.info("[%s] %d songs pending (%d already complete across all heads)", backbone_name, pending_songs, total_songs - pending_songs)

        done = skipped = errors = total_score_rows = total_vec_rows = 0
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
                song_score_rows: list[tuple] = []
                song_vec_rows: list[tuple] = []
                for head_name, missing_combos in heads_missing.items():
                    head_session = head_sessions[head_name]
                    new_score_rows, new_vec_rows = _process_song_head_missing(
                        sid,
                        backbone_name,
                        head_name,
                        head_session,
                        _run_in_batches,
                        _BACKBONE_BATCH_SIZE,
                        patches,
                        missing_combos,
                    )
                    song_score_rows.extend(new_score_rows)
                    song_vec_rows.extend(new_vec_rows)
                if song_score_rows or song_vec_rows:
                    con.executemany(_UPSERT_SQL, song_score_rows)
                    if song_vec_rows:
                        con.executemany(_UPSERT_CTP_VECS_SQL, song_vec_rows)
                    total_score_rows += len(song_score_rows)
                    total_vec_rows += len(song_vec_rows)
                    done += 1
                else:
                    skipped += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
            except Exception as exc:
                errors += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
                tqdm.write(f"  [ERROR] {path.name}: {exc}")

        elapsed = perf_counter() - started
        _log.info(
            "[%s] done=%d skip=%d err=%d score_rows=%d vec_rows=%d  %.0fs",
            backbone_name, done, skipped, errors, total_score_rows, total_vec_rows, elapsed,
        )

    upserted = compute_metrics(
        con,
        backbones=backbone_names,
        bin_modes=BIN_MODES,
        std_thresholds=thresholds,
        heads_filter=heads,
    )
    _log.info("binned_ptc_ctp_metrics rows upserted: %d", upserted)
