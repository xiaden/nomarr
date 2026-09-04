"""Unified head inference for flat and binned embedding-research workflows."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from alive_progress import alive_it

from .cache import binned_ctp_heads as _binned_ctp_heads_cache
from .cache import binned_ptc as _binned_ptc_cache
from .cache import binned_ptc_heads as _binned_ptc_heads_cache
from .cache import flat_heads as _flat_heads_cache
from .cache.flat_vecs import load_matrix as _load_flat_matrix
from .cache_identity import SCORING_SEMANTICS_VERSION
from .config import BACKBONES, HEAD_VRAM_BYTES, HEADS, bootstrap_nomarr, discover_audio, patches_path, song_id
from .head_pooling import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HeadPhaseConfigRecord,
    HeadPhaseManifest,
    pool_head_outputs_over_ptc_boundaries,
)
from .helpers.binning import CTP_SCORE_THRESHOLDS as DEFAULT_CTP_THRESHOLDS
from .helpers.binning import canonical_threshold, global_dist, temporal_segment
from .helpers.cache_utils import build_done_set as _build_done_set
from .pooling import STRATEGIES

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["run_binned", "run_flat", "run_ptc_heads", "run_shared_ptc_head_pooling"]

_log = logging.getLogger(__name__)


def _ctp_enabled() -> bool:
    """True only when ``[archival_ctp] enabled=true`` (the default is disabled).

    Mirrors ``run._ctp_enabled``; read directly from the config here to avoid a
    circular import.  Used to phase-gate CTP-specific head/cache work in this
    legacy classify surface so a disabled default run performs no CTP inference
    and writes no CTP head caches (flat ``"ctp"`` pathway + ``binned_ctp_heads``).
    """
    from .helpers import toml as _toml_mod

    return bool(_toml_mod.load_research_config().get("archival_ctp", {}).get("enabled", False))


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

    ctp_on = _ctp_enabled()
    patch_acts: np.ndarray | None = None
    if ctp_on:
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
        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ptc", sid, ptc_act)
        if ctp_on:
            ctp_act = np.asarray(pool(patch_acts), dtype=np.float32)
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

    ctp_on = _ctp_enabled()
    patch_acts: np.ndarray | None = None
    if ctp_on:
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
        _flat_heads_cache.save(backbone_name, head_name, strategy_name, "ptc", sid, ptc_act)
        if ctp_on:
            ctp_act = np.asarray(pool(patch_acts), dtype=np.float32)
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
    missing_thresholds: frozenset[float],
) -> int:
    """Run a head on patches for exactly the missing std_thresh values.

    Saves results directly to the filesystem cache:

    * ``binned_ctp_heads`` — per-bin mean head activations

    Returns the number of std_thresh values saved.
    """
    if not missing_thresholds:
        return 0

    # CTP head bins (``binned_ctp_heads``) are phase-gated: with ``[archival_ctp]
    # enabled=false`` (the default) no binned_ctp_heads cache rows are produced.
    if not _ctp_enabled():
        return 0

    acts = run_in_batches_fn(
        lambda batch: _run_head_session(head_session, batch),
        patches,
        batch_size,
    ).astype(np.float32)
    if acts.size == 0:
        return 0

    scores = acts[:, 1]
    score_column = scores.reshape(-1, 1).astype(np.float32)

    saved_heads = 0
    for std_thresh in missing_thresholds:
        threshold = float(std_thresh)
        segments = temporal_segment(score_column, threshold, global_dist)

        bin_acts_list: list[np.ndarray] = []
        bin_weights_list: list[int] = []

        for seg in segments:
            indices = seg["indices"]
            if not indices:
                continue

            seg_acts = acts[indices]
            mean_act = seg_acts.mean(axis=0).astype(np.float32)
            bin_acts_list.append(mean_act)
            bin_weights_list.append(len(indices))

        if bin_acts_list:
            acts_arr = np.stack(bin_acts_list).astype(np.float32)
            wts_arr = np.array(bin_weights_list, dtype=np.int32)
            _binned_ctp_heads_cache.save(backbone, head_name, std_thresh, sid, acts_arr, wts_arr)
            saved_heads += 1

    return saved_heads


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
    done_set: set[tuple[str, str, str, float]] | None = None,
) -> tuple[int, int]:
    """Run a head on all patches for all std_thresh values (force path).

    Same filesystem-save behaviour as :func:`_process_song_head_missing`.
    """
    missing: frozenset[float]
    if not force and done_set is not None:
        all_done = all((sid, backbone, head_name, float(std_thresh)) in done_set for std_thresh in std_thresholds)
        if all_done:
            return 0, 0
        missing = frozenset(float(st) for st in std_thresholds if (sid, backbone, head_name, float(st)) not in done_set)
    else:
        missing = frozenset(float(st) for st in std_thresholds)
    return _process_song_head_missing(
        sid, backbone, head_name, head_session, run_in_batches_fn, batch_size, patches, missing
    )


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
    """Backward-compatible wrapper for the shared-boundary PTC head phase.

    Delegates to :func:`run_shared_ptc_head_pooling`, the explicitly named
    shared PTC boundary phase that pools classifier head outputs over the
    EffNet PTC cache boundaries only (never the CTP segmenter, never
    head-specific bins), and discards the returned manifest.  The legacy
    default ``backbones=None`` runs every configured backbone.
    """
    backbone_names = backbones or list(BACKBONES)
    run_shared_ptc_head_pooling(
        con,
        song_ids=song_ids,
        backbones=backbone_names,
        heads=heads,
        bin_modes=None,
        thresholds=None,
        force=force,
        device=device,
        head_sessions=head_sessions,
    )


def _head_phase_record(
    backbone_name: str,
    head_name: str,
    bin_mode: str,
    std_thresh: float,
    stats: dict[str, Any],
) -> HeadPhaseConfigRecord:
    """Build a frozen per-config record from the mutable per-config stats."""
    return HeadPhaseConfigRecord(
        backbone=backbone_name,
        head=head_name,
        bin_mode=bin_mode,
        threshold=float(std_thresh),
        status=str(stats["status"]),
        reason=str(stats["reason"]),
        n_songs=int(stats["n_songs"]),
        n_pooled=int(stats["n_pooled"]),
        finite=bool(stats["finite"]),
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
    )


def run_shared_ptc_head_pooling(
    con,  # noqa: ARG001  (reserved for future head-phase persistence; Phase 1 is pure + cache-only)
    *,
    song_ids: frozenset[str] | None = None,
    backbones: list[str] | None = None,
    heads: list[str] | None = None,
    bin_modes: list[str] | None = None,
    thresholds: list[float] | None = None,
    force: bool = False,
    device: str = "cpu",
    head_sessions: dict[str, dict[str, Any]] | None = None,
) -> HeadPhaseManifest:
    """LEGACY INTERIM (Plan E, Phase 1 D1): live-ONNX/inclusive-range head pooling.

    Retained callable through Phase 4 for live-ONNX/inclusive-range compatibility.
    It is CACHE/MANIFEST-ONLY w.r.t. persistence (it no longer writes any
    ``head_phase_provenance`` rows) and never calls the canonical CPU runner or
    canonical persistence in ``common/head_analysis.py``.  The ACTIVE canonical
    CPU surface is ``common/head_analysis.run_shared_ptc_head_pooling``; Phase 4
    retires this legacy runner.

    The explicitly named **shared PTC boundary** head phase.  It consumes ONLY
    the EffNet PTC cache boundaries (``bin_start_idx`` / ``bin_end_idx`` /
    ``weights``) and NEVER calls the CTP score-stream segmenter
    (``strategy_ctp.segment_fn``) and NEVER creates head-specific bins.  CTP
    cache paths are not repurposed.

    Deterministic ordering: backbones, heads, bin modes, thresholds, and song
    IDs are all processed in sorted order, and skip/error reasons are recorded
    in the returned :class:`HeadPhaseManifest`.  This phase is optional and
    non-blocking — primary EffNet PTC-vs-medoid analysis always completes
    regardless of whether head models or head caches are present
    (``primary_analysis_succeeded=True``).  It never mutates the primary corpus
    or primary winner grid.
    """
    bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    backbone_names = sorted(set(backbones if backbones is not None else ["effnet"]))
    requested_heads = set(heads) if heads is not None else None
    sel_modes = set(bin_modes) if bin_modes is not None else None
    sel_thresholds = {canonical_threshold(t) for t in thresholds} if thresholds is not None else None

    # Gather EffNet PTC boundary combos from the PTC cache (never CTP).
    ptc_keys = _binned_ptc_cache.list_done_keys()  # (sid, backbone, bin_mode, std_thresh)
    by_bb: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for sid_k, bb_k, bm_k, st_k in ptc_keys:
        if bb_k not in backbone_names:
            continue
        if sel_modes is not None and bm_k not in sel_modes:
            continue
        st_c = canonical_threshold(st_k)
        if sel_thresholds is not None and st_c not in sel_thresholds:
            continue
        if song_ids is not None and sid_k not in song_ids:
            continue
        by_bb.setdefault(bb_k, {}).setdefault(sid_k, []).append((bm_k, st_c))

    skip_reasons: list[tuple[str, str]] = []
    records: list[HeadPhaseConfigRecord] = []

    for backbone_name in backbone_names:
        sids_with_combos = by_bb.get(backbone_name)
        if not sids_with_combos:
            skip_reasons.append((f"backbone:{backbone_name}", "no EffNet PTC cache entries"))
            continue

        head_map = {
            head: model
            for head, model in HEADS.get(backbone_name, {}).items()
            if requested_heads is None or head in requested_heads
        }
        if not head_map:
            skip_reasons.append((f"backbone:{backbone_name}", "no configured heads"))
            continue

        # Deterministic config space: sorted heads x sorted union of combos.
        union_combos = sorted({combo for combos in sids_with_combos.values() for combo in combos})

        loaded_sessions: dict[str, Any] = {}
        for head_name in sorted(head_map):
            if head_sessions is not None:
                session = head_sessions.get(backbone_name, {}).get(head_name)
                if session is None:
                    skip_reasons.append((f"{backbone_name}/{head_name}", "no cached head session"))
                    continue
                loaded_sessions[head_name] = session
            else:
                try:
                    loaded_sessions[head_name] = create_session(
                        head_map[head_name],
                        device=device,
                        vram_limit_bytes=HEAD_VRAM_BYTES,
                    )
                except Exception as exc:
                    skip_reasons.append((f"{backbone_name}/{head_name}", f"failed to load head model: {exc}"))

        # Per-config mutable stats.
        stats: dict[tuple[str, str, float], dict[str, Any]] = {}
        for head_name in sorted(head_map):
            for bm, st in union_combos:
                stats[(head_name, bm, st)] = {
                    "status": "skipped",
                    "reason": "",
                    "n_songs": 0,
                    "n_pooled": 0,
                    "finite": True,
                }

        if not loaded_sessions:
            # Head models/caches absent — record per-config skip reasons, never raise.
            for key in stats:
                stats[key]["reason"] = "head model/session unavailable"
            for key, s in stats.items():
                records.append(_head_phase_record(backbone_name, key[0], key[1], key[2], s))
            continue

        all_combos = set(union_combos)
        ptc_heads_done: dict[tuple[str, str, float], frozenset[str]] = {
            (head_name, bin_mode, std_thresh): _build_done_set(
                _binned_ptc_heads_cache.config_dir(backbone_name, head_name, bin_mode, std_thresh),
                suffix=".npz",
            )
            for head_name in loaded_sessions
            for bin_mode, std_thresh in all_combos
        }

        sid_list = sorted(sids_with_combos)

        def _mark_song_skip(reason: str, _stats: dict = stats) -> None:
            for key in _stats:
                _stats[key]["n_songs"] = int(_stats[key]["n_songs"]) + 1
                if not _stats[key]["reason"]:
                    _stats[key]["reason"] = reason

        def _bump_combo(
            bmode: str,
            sthresh: float,
            *,
            pooled: bool,
            reason: str,
            _head_names: dict[str, Any] = loaded_sessions,
            _stats: dict = stats,
        ) -> None:
            """Increment n_songs (and n_pooled when *pooled*) for one combo's configs."""
            for head_name in _head_names:
                key = (head_name, bmode, sthresh)
                _stats[key]["n_songs"] = int(_stats[key]["n_songs"]) + 1
                if pooled:
                    _stats[key]["n_pooled"] = int(_stats[key]["n_pooled"]) + 1
                if not _stats[key]["reason"]:
                    _stats[key]["reason"] = reason

        for sid in sid_list:
            combos = sids_with_combos[sid]
            sidecar = patches_path(sid, backbone_name)
            if not sidecar.exists():
                _mark_song_skip("patch sidecar missing")
                continue
            try:
                patches = np.load(str(sidecar)).astype(np.float32)
            except Exception:
                _mark_song_skip("patch sidecar unreadable")
                continue
            if patches.size == 0:
                _mark_song_skip("empty patch sidecar")
                continue

            pending: dict[tuple[str, float], tuple[list[str], np.ndarray, np.ndarray, np.ndarray]] = {}
            # True when at least one combo for this song was counted as pooled (cached-valid
            # heads) or queued for recompute (pending); used to decide the all-nothing skip.
            song_contributed = False
            for bin_mode, std_thresh in combos:
                if force:
                    # force=True recomputes everything: no head is treated as cached-valid.
                    cached_valid_heads: list[str] = []
                    missing_heads: list[str] = list(loaded_sessions)
                else:
                    # Partition this combo's heads. A head whose entry is cached AND carries
                    # non-stale provenance (cached-valid) counts as pooled for this song. Any
                    # missing head, or a cached-but-stale head (is_done true but provenance
                    # rejected), goes to pending for recompute — never silently reused and never
                    # double-counted. This fixes partial-cache accounting: previously a combo
                    # with some heads cached and some missing sent only the missing heads to
                    # pending, leaving the cached-valid heads uncounted (status='skipped'
                    # reason='' n_songs=0 n_pooled=0) and skipping their provenance validation.
                    cached_valid_heads = [
                        h
                        for h in loaded_sessions
                        if _binned_ptc_heads_cache.is_done(
                            backbone_name,
                            h,
                            bin_mode,
                            std_thresh,
                            sid,
                            done_set=ptc_heads_done.get((h, bin_mode, std_thresh)),
                        )
                        and _binned_ptc_heads_cache.check_cache_valid(backbone_name, h, bin_mode, std_thresh, sid)
                    ]
                    missing_heads = [h for h in loaded_sessions if h not in cached_valid_heads]
                if cached_valid_heads:
                    # Count the cached-valid heads as pooled for this song (only those heads,
                    # not the missing/stale ones queued below), so per-threshold coverage stays
                    # accurate on incremental re-runs regardless of partial cache population.
                    _bump_combo(
                        bin_mode,
                        std_thresh,
                        pooled=True,
                        reason="head arrays cached and valid",
                        _head_names=dict.fromkeys(cached_valid_heads),
                    )
                    song_contributed = True
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
                    # Legacy PTC cache lacking bin_start_idx/bin_end_idx (or unreadable):
                    # record a distinct skip reason and bump n_songs for the affected combos
                    # instead of silently dropping the config with provenance status='skipped'
                    # and an empty reason.
                    # Scope the legacy-format bump to ONLY the missing heads.  The cached-valid
                    # heads (if any) were already counted as pooled for this song at the top of the
                    # loop, so counting all heads here again with the all-heads default would
                    # double-count their n_songs (one song reported n_songs=2 for a cached head).
                    _bump_combo(
                        bin_mode,
                        std_thresh,
                        pooled=False,
                        reason="PTC cache lacks boundary keys (legacy format)",
                        _head_names=dict.fromkeys(missing_heads),
                    )
                    # Mark the song as contributed so the subsequent all-nothing skip
                    # (_mark_song_skip "no PTC boundaries to pool") does not fire and
                    # double-count n_songs when ALL of a song's combos are legacy-format.
                    song_contributed = True
                    continue
                pending[(bin_mode, std_thresh)] = (missing_heads, bin_start, bin_end, ptc_wts)
                song_contributed = True

            if not pending and not song_contributed:
                _mark_song_skip("no PTC boundaries to pool")
                continue
            if not pending:
                continue

            # Run head inference once per head per song (shared across all combos).
            needed_heads = sorted({h for miss, _, _, _ in pending.values() for h in miss})
            head_acts: dict[str, np.ndarray] = {}
            for head_name in needed_heads:
                session = loaded_sessions[head_name]
                try:

                    def _run_head_batch(batch: np.ndarray, _session: Any = session) -> np.ndarray:
                        return _run_head_session(_session, batch)

                    acts = _run_in_batches(_run_head_batch, patches, _BACKBONE_BATCH_SIZE).astype(np.float32)
                    head_acts[head_name] = acts
                except Exception as exc:
                    skip_reasons.append((f"{backbone_name}/{head_name}/{sid}", f"head inference failed: {exc}"))

            if not head_acts:
                _mark_song_skip("head inference failed")
                continue

            for (bin_mode, std_thresh), (missing_heads, bin_start, bin_end, ptc_wts) in pending.items():
                for head_name in missing_heads:
                    if head_name not in head_acts:
                        continue
                    key = (head_name, bin_mode, std_thresh)
                    stats[key]["n_songs"] = int(stats[key]["n_songs"]) + 1
                    try:
                        result = pool_head_outputs_over_ptc_boundaries(
                            head_acts[head_name], bin_start, bin_end, ptc_wts
                        )
                    except ValueError as exc:
                        stats[key]["status"] = "error"
                        stats[key]["reason"] = f"boundary validation failed: {exc}"
                        stats[key]["finite"] = False
                        continue
                    _binned_ptc_heads_cache.save(
                        backbone_name,
                        head_name,
                        bin_mode,
                        std_thresh,
                        sid,
                        result.acts,
                        result.weights,
                        bin_start_idx=result.bin_start_idx,
                        bin_end_idx=result.bin_end_idx,
                        boundary_source=result.boundary_source,
                        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
                        finite=result.finite,
                    )
                    stats[key]["n_pooled"] = int(stats[key]["n_pooled"]) + 1
                    stats[key]["status"] = "done"
                    if not result.finite:
                        skip_reasons.append(
                            (f"{backbone_name}/{head_name}/{bin_mode}/{std_thresh}/{sid}", "non-finite pooled output")
                        )

        for key, s in stats.items():
            records.append(_head_phase_record(backbone_name, key[0], key[1], key[2], s))

    done = sum(1 for r in records if r.status == "done")
    skipped = sum(1 for r in records if r.status == "skipped")
    errors = sum(1 for r in records if r.status == "error")

    manifest_sids = tuple(sorted({s for combos_by_sid in by_bb.values() for s in combos_by_sid}))
    manifest_heads = tuple(sorted({r.head for r in records}))
    manifest_modes = tuple(sorted({r.bin_mode for r in records}))
    manifest_thresholds = tuple(sorted({r.threshold for r in records}))

    return HeadPhaseManifest(
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        backbones=tuple(backbone_names),
        heads=manifest_heads,
        bin_modes=manifest_modes,
        thresholds=manifest_thresholds,
        song_ids=manifest_sids,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        results=tuple(records),
        skip_reasons=tuple(skip_reasons),
        done=done,
        skipped=skipped,
        errors=errors,
        finite=all(r.finite for r in records),
        primary_analysis_succeeded=True,
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
    thresholds_by_backbone: dict[str, list[float]] | None = None,
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
    if thresholds_by_backbone:
        all_thresholds: frozenset[float] = frozenset(
            st for thresholds in thresholds_by_backbone.values() for st in thresholds
        )
    else:
        all_thresholds = frozenset(float(st) for st in DEFAULT_CTP_THRESHOLDS)

    # Build (sid, backbone, head) -> set[done std_thresh] from filesystem cache
    if not force:
        ctp_heads_done = _binned_ctp_heads_cache.list_done_keys()  # (sid, backbone, head, std_thresh)
        done_thresholds_by_key: dict[tuple[str, str, str], set[float]] = {}
        for sid_d, bb_d, head_d, st_d in ctp_heads_done:
            done_thresholds_by_key.setdefault((sid_d, bb_d, head_d), set()).add(st_d)
    else:
        done_thresholds_by_key = {}

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

        # Build work dict: song_path → {head_name: frozenset[missing std_thresh]}
        # Only include entries where at least one threshold is missing.
        work: dict[Path, dict[str, frozenset[float]]] = {}
        for p in audio_paths:
            sid = song_id(p)
            heads_missing: dict[str, frozenset[float]] = {}
            for head_name in loaded_head_sessions:
                done_c = done_thresholds_by_key.get((sid, backbone_name, head_name), set())
                missing = all_thresholds - done_c if not force else all_thresholds
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
                total_saved_heads = 0
                for head_name, missing_thresholds in heads_missing.items():
                    head_session = loaded_head_sessions[head_name]
                    saved = _process_song_head_missing(
                        sid,
                        backbone_name,
                        head_name,
                        head_session,
                        _run_in_batches,
                        _BACKBONE_BATCH_SIZE,
                        patches,
                        missing_thresholds,
                    )
                    total_saved_heads += saved
                if total_saved_heads > 0:
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
