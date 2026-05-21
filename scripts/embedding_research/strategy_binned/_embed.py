"""Binned embed() entrypoint."""

from __future__ import annotations

import logging as _logging
import time as _time
from collections import defaultdict as _defaultdict
from pathlib import Path as _Path

import numpy as _np
from tqdm import tqdm as _tqdm

from .. import db as _db
from ..config import BACKBONES as _BACKBONES
from ..config import HEAD_VRAM_BYTES as _HEAD_VRAM_BYTES
from ..config import HEADS as _HEADS
from ..config import patches_path as _patches_path
from ..config import stratify_songs as _stratify_songs
from ..helpers.binning import BIN_MODES, DIST_FNS as _DIST_FNS, STD_THRESHOLDS, temporal_segment
from ..similarity import l2_normalise as _l2_normalise
from ._cache import list_done_keys as _list_cache_done
from ._cache import save as _cache_save
from ._calibrate import _calibrate, _load_cached_calibration
from ._features import _extract_patch_features, _run_head_batch
from ._pool import _pool_segment

_log = _logging.getLogger(__name__)

_SQL_PATCH_FEATURES = """
INSERT INTO patch_features
  (song_id, patch_idx, rms, spectral_centroid, onset_strength, chroma_key)
VALUES (?,?,?,?,?,?)
ON CONFLICT (song_id, patch_idx) DO UPDATE SET
  rms=excluded.rms,
  spectral_centroid=excluded.spectral_centroid,
  onset_strength=excluded.onset_strength,
  chroma_key=excluded.chroma_key
"""


def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
) -> None:
    """Embed missing binned song representations and write them to the file cache."""
    from nomarr.components.ml.onnx.ml_session_comp import create_session as _create_session

    _log.info("Loading song list from DB ...")
    _t0_prep = _time.perf_counter()
    all_songs = _db.load_all_songs(con)
    songs = (
        [s for s in all_songs if str(s["song_id"]) in song_ids]
        if song_ids is not None
        else all_songs
    )
    _log.info("  -> %d songs loaded  (%.1fs)", len(songs), _time.perf_counter() - _t0_prep)
    song_paths = [_Path(song["path"]) for song in songs]
    bb_names = list(backbones) if backbones is not None else list(_BACKBONES)

    all_combos_set: frozenset[tuple[str, float]] = frozenset(
        (bm, st) for bm in BIN_MODES for st in STD_THRESHOLDS
    )

    if not force:
        _log.info("Scanning file cache for completed binned embeddings ...")
        _t0_done = _time.perf_counter()
        done_by_key: dict[tuple[str, str], set[tuple[str, float]]] = {}
        for sid_d, bb_d, bm_d, st_d in _list_cache_done():
            key = (sid_d, bb_d)
            if key not in done_by_key:
                done_by_key[key] = set()
            done_by_key[key].add((bm_d, float(st_d)))
        _log.info(
            "  -> %d (song×backbone) pairs already done  (%.1fs)",
            len(done_by_key),
            _time.perf_counter() - _t0_done,
        )
    else:
        done_by_key = {}

    for backbone in bb_names:
        _log.info("[%s] ── backbone embed start ──", backbone)
        t_backbone = _time.perf_counter()

        cached_calibration = None if force else _load_cached_calibration(con, backbone)
        if cached_calibration is not None:
            _log.info("[%s] Calibration loaded from cache (%d mode(s))", backbone, len(cached_calibration))
            calibration = cached_calibration
        else:
            _log.info("[%s] Computing distance-threshold calibration ...", backbone)
            calibration = _calibrate(con, backbone, song_paths, force=force)
            _log.info("[%s] Calibration done (%d mode(s))", backbone, len(calibration))

        head_sessions: dict[str, object] = {}
        for head_name, model_path in _HEADS.get(backbone, {}).items():
            try:
                head_sessions[head_name] = _create_session(
                    model_path,
                    device=device,
                    vram_limit_bytes=_HEAD_VRAM_BYTES,
                )
            except Exception as exc:
                _log.warning("[WARN] Could not load head %s for %s: %s", head_name, backbone, exc)

        work: list[tuple[dict, frozenset[tuple[str, float]]]] = []
        for s in songs:
            sid = str(s["song_id"])
            missing = all_combos_set - done_by_key.get((sid, backbone), set())
            if missing:
                work.append((s, missing))

        done = 0
        skipped = 0
        errors = 0
        started_at = _time.perf_counter()
        _log.info("[%s] %d songs pending (%d already complete)", backbone, len(work), len(songs) - len(work))
        progress = _tqdm(work, desc=f"[{backbone}] binned-embed", unit="song")
        for song, missing_combos in progress:
            sid = str(song["song_id"])
            path = _Path(song["path"])
            sidecar = _patches_path(sid, backbone)
            if not sidecar.exists():
                skipped += 1
                progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)
                continue

            try:
                raw_all = _np.load(str(sidecar)).astype(_np.float32)
                if len(raw_all) < 2:
                    skipped += 1
                    progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)
                    continue

                norm_all = _l2_normalise(raw_all)
                n_patches = len(raw_all)

                # Write patch-level acoustic features directly to DB (small, scalar only)
                if not _db.patch_features_done(con, sid):
                    feats = _extract_patch_features(path, n_patches)
                    if feats is not None:
                        rows = [
                            (
                                sid,
                                idx,
                                f.get("rms"),
                                f.get("spectral_centroid"),
                                f.get("onset_strength"),
                                f.get("chroma_key"),
                            )
                            for idx, f in enumerate(feats)
                        ]
                        con.execute("BEGIN")
                        con.executemany(_SQL_PATCH_FEATURES, rows)
                        con.execute("COMMIT")

                bulk_vecs: list[tuple] = []
                bulk_heads: list[tuple] = []
                # (bin_mode, std_thresh, bin_id, mean_vec_raw, seg_size)
                head_inputs: list[tuple] = []
                wrote_any = False

                for bin_mode, std_thresh in missing_combos:
                    cal = calibration.get(bin_mode)
                    p50 = cal.get("p50") if cal is not None else None
                    threshold = std_thresh * (p50 if p50 is not None else 0.1)
                    segments = temporal_segment(norm_all, threshold, _DIST_FNS[bin_mode])
                    if not segments:
                        continue

                    for bin_id, seg in enumerate(segments):
                        pooled = _pool_segment(raw_all, norm_all, seg["indices"])
                        outlier_count = int(seg["outlier_count"])

                        for pool_strategy, pdata in pooled.items():
                            bulk_vecs.append(
                                (
                                    sid,
                                    backbone,
                                    bin_mode,
                                    std_thresh,
                                    bin_id,
                                    pool_strategy,
                                    pdata["vec_raw"].astype(_np.float32).tobytes(),
                                    pdata["vec_norm"].astype(_np.float32).tobytes(),
                                    pdata["weight"],
                                    outlier_count,
                                )
                            )

                        head_inputs.append(
                            (bin_mode, std_thresh, bin_id, pooled["mean"]["vec_raw"], len(seg["indices"]))
                        )

                    wrote_any = True

                # Batch head inference: one ONNX call per head across all combos×segments
                if head_inputs and head_sessions:
                    batch_mat = _np.stack([x[3] for x in head_inputs]).astype(_np.float32)
                    for head_name, session in head_sessions.items():
                        try:
                            acts = _run_head_batch(session, batch_mat)  # [N, n_classes]
                            for i, (bm, st, bid, _, seg_size) in enumerate(head_inputs):
                                bulk_heads.append(
                                    (
                                        sid,
                                        backbone,
                                        head_name,
                                        bm,
                                        st,
                                        bid,
                                        acts[i].astype(_np.float32).tobytes(),
                                        seg_size,
                                    )
                                )
                        except Exception:
                            continue

                # Write one npz per (bin_mode, std_thresh) combo
                if bulk_vecs or bulk_heads:
                    vecs_by_combo: dict[tuple, list] = _defaultdict(list)
                    heads_by_combo: dict[tuple, list] = _defaultdict(list)
                    for row in bulk_vecs:
                        vecs_by_combo[(row[2], row[3])].append(row)
                    for row in bulk_heads:
                        heads_by_combo[(row[3], row[4])].append(row)
                    for (bm, st), vecs in vecs_by_combo.items():
                        _cache_save(
                            backbone, bm, st, sid,
                            vecs, heads_by_combo.get((bm, st), []),
                        )

                del raw_all, norm_all
                if wrote_any:
                    done += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                _tqdm.write(f"[ERROR] {path.name}: {exc}")

            progress.set_postfix(done=done, skip=skipped, err=errors, refresh=False)

        elapsed = _time.perf_counter() - started_at
        _log.info("[%s] ── backbone embed done  total=%.0fs ──", backbone, _time.perf_counter() - t_backbone)
        _log.info(
            "[%s] done=%d skip=%d err=%d  %.0fs  (%.2f songs/s)",
            backbone,
            done,
            skipped,
            errors,
            elapsed,
            len(songs) / max(elapsed, 1),
        )
