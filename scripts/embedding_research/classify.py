"""Unified head inference for flat and binned embedding-research workflows."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import numpy as np
from alive_progress import alive_bar, alive_it

from .cache import binned_ctp as _binned_ctp_cache
from .cache import binned_ctp_heads as _binned_ctp_heads_cache
from .cache import binned_ptc as _binned_ptc_cache
from .cache import binned_ptc_heads as _binned_ptc_heads_cache
from .cache import flat_heads as _flat_heads_cache
from .cache.flat_vecs import load_matrix as _load_flat_matrix
from .config import BACKBONES, HEAD_VRAM_BYTES, HEADS, bootstrap_nomarr, discover_audio, patches_path, song_id
from .helpers.binning import BIN_MODES, global_dist, temporal_segment
from .helpers.binning import CTP_SCORE_THRESHOLDS as DEFAULT_CTP_THRESHOLDS
from .helpers.binning import DIST_THRESHOLDS as DEFAULT_STD_THRESHOLDS
from .helpers.cache_utils import build_done_set as _build_done_set
from .pooling import STRATEGIES

__all__ = ["run_binned", "run_flat", "run_ptc_heads"]

_log = logging.getLogger(__name__)

from scripts.embedding_research.strategy_binned._constants import _BIN_POOL_STRATEGIES as _BIN_POOL_FNS


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

    saved_heads = saved_vecs = 0
    for bin_mode, std_thresh in missing_combos:
        # std_thresh is an absolute half-width in score space: a patch whose
        # score differs from the current segment mean by more than std_thresh
        # starts a new bin.  This is corpus- and song-variance-independent —
        # a song that doesn't vary on this head simply produces one bin.
        threshold = float(std_thresh)
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
                vec_rows_for_combo.append(
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
    return _process_song_head_missing(
        sid, backbone, head_name, head_session, run_in_batches_fn, batch_size, patches, missing
    )


def _compute_ptc_head_acts_for_bins(
    acts: np.ndarray,
    bin_start_idx: np.ndarray,
    bin_end_idx: np.ndarray,
) -> np.ndarray:
    """Return ``[n_bins, C]`` mean head activations from patch-level acts.

    For each bin, averages *acts* over the inclusive patch range
    ``[bin_start_idx[i], bin_end_idx[i]]``.  Bins with invalid indices
    (``< 0`` or start > end) produce a zero row.
    """
    n_bins = len(bin_start_idx)
    n_classes = acts.shape[1]
    result = np.zeros((n_bins, n_classes), dtype=np.float32)
    for i in range(n_bins):
        s, e = int(bin_start_idx[i]), int(bin_end_idx[i])
        if s >= 0 and e >= s:
            seg = acts[s : e + 1]
            if seg.shape[0] > 0:
                result[i] = seg.mean(axis=0)
    return result


def run_ptc_heads(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    device: str = "cpu",
    head_sessions: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Inject per-bin PTC head activations into the binned_ptc filesystem cache.

    For each song that has PTC-binned embeddings, runs head inference on all
    patches and averages activations per PTC bin (using the ``bin_start_idx``
    and ``bin_end_idx`` boundaries already stored in the cache npz).

    Skips ``(backbone, bin_mode, std_thresh, song_id)`` combos where all
    requested head arrays are already present, unless *force* is ``True``.

    If *head_sessions* is provided (``{backbone: {head_name: session}}``) those
    sessions are used directly and ``create_session`` is not called.
    """
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    backbone_names = backbones or list(BACKBONES)
    ptc_keys = _binned_ptc_cache.list_done_keys()  # (sid, backbone, bin_mode, std_thresh)

    # Group: backbone -> sid -> [(bin_mode, std_thresh)]
    ptc_by_bb: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for sid_k, bb_k, bm_k, st_k in ptc_keys:
        if bb_k not in backbone_names:
            continue
        if song_ids is not None and sid_k not in song_ids:
            continue
        ptc_by_bb.setdefault(bb_k, {}).setdefault(sid_k, []).append((bm_k, st_k))

    for backbone_name in backbone_names:
        sids_with_combos = ptc_by_bb.get(backbone_name)
        if not sids_with_combos:
            _log.info("[%s] No PTC cache entries — skipping PTC head phase", backbone_name)
            continue

        head_map = {
            head: model for head, model in HEADS.get(backbone_name, {}).items() if heads is None or head in heads
        }
        if not head_map:
            _log.info("[%s] No heads configured — skipping PTC head phase", backbone_name)
            continue

        loaded_sessions: dict[str, Any] = {}
        for head_name, head_model_path in head_map.items():
            if head_sessions is not None:
                session = head_sessions.get(backbone_name, {}).get(head_name)
                if session is None:
                    _log.error("[%s/%s] No cached session — skipping", backbone_name, head_name)
                    continue
                loaded_sessions[head_name] = session
            else:
                try:
                    loaded_sessions[head_name] = create_session(
                        head_model_path,
                        device=device,
                        vram_limit_bytes=HEAD_VRAM_BYTES,
                    )
                except Exception as exc:
                    _log.error("[%s/%s] Failed to load head: %s", backbone_name, head_name, exc)

        if not loaded_sessions:
            continue

        done = skipped = errors = 0
        started = perf_counter()
        sid_list = sorted(sids_with_combos)

        # Pre-build done sets — one frozenset per (head, bin_mode, std_thresh) so
        # is_done() checks are O(1) set membership, not one stat() per song.
        all_combos: set[tuple[str, float]] = {
            combo for combos in sids_with_combos.values() for combo in combos
        }
        ptc_heads_done: dict[tuple[str, str, float], frozenset[str]] = {
            (head_name, bin_mode, std_thresh): _build_done_set(
                _binned_ptc_heads_cache.config_dir(backbone_name, head_name, bin_mode, std_thresh),
                suffix=".npz",
            )
            for head_name in loaded_sessions
            for bin_mode, std_thresh in all_combos
        }

        pbar = alive_it(sid_list, title=f"  [{backbone_name}] PTC-heads")

        for sid in pbar:
            combos = sids_with_combos[sid]
            sidecar = patches_path(sid, backbone_name)
            if not sidecar.exists():
                skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
                continue

            try:
                patches = np.load(str(sidecar)).astype(np.float32)
            except Exception:
                skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
                continue

            if patches.size == 0:
                skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
                continue

            # For each (bin_mode, std_thresh) combo: use is_done() for the skip
            # check, then load the PTC npz only when there are missing heads.
            pending: dict[tuple[str, float], tuple[list[str], np.ndarray, np.ndarray, np.ndarray]] = {}
            for bin_mode, std_thresh in combos:
                missing_heads = (
                    list(loaded_sessions)
                    if force
                    else [
                        h
                        for h in loaded_sessions
                        if not _binned_ptc_heads_cache.is_done(
                            backbone_name,
                            h,
                            bin_mode,
                            std_thresh,
                            sid,
                            done_set=ptc_heads_done.get((h, bin_mode, std_thresh)),
                        )
                    ]
                )
                if not missing_heads:
                    continue
                ptc_path = _binned_ptc_cache.cache_path(backbone_name, bin_mode, std_thresh, sid)
                if not ptc_path.exists():
                    continue
                try:
                    ptc_data = np.load(str(ptc_path))
                    bin_start = ptc_data["bin_start_idx"].astype(np.int32)
                    bin_end = ptc_data["bin_end_idx"].astype(np.int32)
                    ptc_wts = ptc_data["weights"].astype(np.int32)
                    ptc_data.close()
                except (EOFError, OSError, ValueError, KeyError):
                    continue
                pending[(bin_mode, std_thresh)] = (missing_heads, bin_start, bin_end, ptc_wts)

            if not pending:
                skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
                continue

            # Run head inference once per head per song (shared across all combos)
            needed_heads = sorted({h for miss, _, _, _ in pending.values() for h in miss})
            head_acts: dict[str, np.ndarray] = {}
            for head_name in needed_heads:
                session = loaded_sessions[head_name]
                try:
                    acts = _run_in_batches(
                        lambda batch, _s=session: _run_head_session(_s, batch),
                        patches,
                        _BACKBONE_BATCH_SIZE,
                    ).astype(np.float32)
                    head_acts[head_name] = acts
                except Exception as exc:
                    _log.error("[%s/%s/%s] head inference failed: %s", backbone_name, head_name, sid, exc)

            if not head_acts:
                errors += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
                continue

            wrote_any = False
            for (bin_mode, std_thresh), (missing_heads, bin_start, bin_end, ptc_wts) in pending.items():
                for head_name in missing_heads:
                    if head_name not in head_acts:
                        continue
                    bin_acts = _compute_ptc_head_acts_for_bins(head_acts[head_name], bin_start, bin_end)
                    _binned_ptc_heads_cache.save(backbone_name, head_name, bin_mode, std_thresh, sid, bin_acts, ptc_wts)
                    wrote_any = True

            if wrote_any:
                done += 1
            else:
                skipped += 1
            pbar.text(f"done={done} skip={skipped} err={errors}")

        elapsed = perf_counter() - started
        _log.info(
            "[%s] PTC-heads done=%d skip=%d err=%d  %.0fs",
            backbone_name,
            done,
            skipped,
            errors,
            elapsed,
        )


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
        fully_done_flat = _flat_heads_cache.list_done_keys()  # (song_id, backbone, head_name, strategy)
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

        # Skip the expensive pre-load if every (song, head) combo is already cached.
        any_pending = any(
            bool(all_strategies - done_strats_by_key.get((song_id(p), backbone_name, head_name), set()))
            for p in audio_paths
            for head_name in head_map
        )
        if not any_pending:
            _log.info("[%s] All heads fully cached — skipping pre-load", backbone_name)
            continue

        _log.info("[%s] Pre-loading pooled vectors from Filesystem ...", backbone_name)
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
            pbar = alive_it(work_flat, title=f"  [{backbone_name}/{head_name}]")
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
                    pbar.text(f"done={n_done} skip={skipped} err={errors}")
                except Exception as exc:
                    errors += 1
                    pbar.text(f"done={n_done} skip={skipped} err={errors}")
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
        all_combos_binned = frozenset((bm, float(st)) for bm in BIN_MODES for st in DEFAULT_CTP_THRESHOLDS)

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
        pbar = alive_it(work.items(), title=f"[{backbone_name}] binned-classify")
        for path, heads_missing in pbar:
            sid = song_id(path)
            sidecar = patches_path(sid, backbone_name)
            if not sidecar.exists():
                skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
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
                pbar.text(f"done={done} skip={skipped} err={errors}")
            except Exception as exc:
                errors += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
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

    run_ptc_heads(
        con,
        song_ids=song_ids,
        force=force,
        backbones=backbone_names,
        heads=heads,
        device=device,
        head_sessions=head_sessions,
    )
