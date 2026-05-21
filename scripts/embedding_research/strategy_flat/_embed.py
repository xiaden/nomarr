"""Flat-pool embed: _embed_song and embed."""

from __future__ import annotations

import logging as _logging
from pathlib import Path as _Path
from typing import Any as _Any
from typing import cast as _cast

import numpy as _np
from tqdm import tqdm as _tqdm

from nomarr.helpers.time_helper import internal_ms as _internal_ms

from ..config import BACKBONES as _BACKBONES
from ..config import PATCHES_DIR as _PATCHES_DIR
from ..config import bootstrap_nomarr as _bootstrap_nomarr
from ..config import discover_audio as _discover_audio
from ..config import patches_path as _patches_path
from ..config import path_to_meta as _path_to_meta
from ..config import song_id as _song_id
from ..db import query_embedded_configs as _query_embedded_configs
from ..db import song_exists as _song_exists
from ..db import upsert_pooled as _upsert_pooled
from ..db import upsert_song as _upsert_song
from ..pooling import STRATEGIES as _STRATEGIES

_log = _logging.getLogger(__name__)


def _embed_song(
    path: _Path,
    backbone_name: str,
    backbone_cfg: dict,
    load_audio_fn,
    preprocess_fn,
    session,
    run_in_batches_fn,
    batch_size: int,
    con,
    embedded_configs: set[tuple[str, str]],
    *,
    force: bool = False,
) -> bool:
    """
    Compute embeddings for one song+backbone. Returns True if work was done.
    Skips if all pooled vectors already exist in the pre-built cache (unless
    force=True). Session must be pre-created by the caller (created once per
    backbone, not per song).
    """
    sid = _song_id(path)

    # Check if all strategies already done
    if not force and all((backbone_name, strategy_name) in embedded_configs for strategy_name in _STRATEGIES):
        return False

    # ── Register song if new ──────────────────────────────────────────────────
    if not _song_exists(con, sid):
        meta = _path_to_meta(path)
        _upsert_song(con, sid, meta["path"], meta["artist"], meta["album"], meta["title"], meta.get("genre", "unknown"))

    # ── Load audio via nomarr ─────────────────────────────────────────────────
    try:
        result = load_audio_fn(str(path), target_sr=16000)
        waveform = result.waveform
    except Exception as exc:
        raise RuntimeError(f"Audio load failed: {path}") from exc

    # ── Preprocess ────────────────────────────────────────────────────────────
    patches = preprocess_fn(waveform, backbone_cfg["backbone_name"])
    if patches is None or len(patches) == 0:
        return False

    # ── Backbone inference ────────────────────────────────────────────────────
    def _predict(batch):
        return session.run(["embeddings"], {"melspectrogram": batch})[0]

    embeddings = run_in_batches_fn(_predict, patches, batch_size)  # [n_patches, dim]

    # ── Save raw patches as sidecar (skip if exists and not force) ────────────
    sidecar = _patches_path(sid, backbone_name)
    if force or not sidecar.exists():
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        _np.save(str(sidecar), embeddings.astype(_np.float32))

    # ── Pool and upsert into DuckDB ───────────────────────────────────────────
    for strategy_name, pool_fn in _STRATEGIES.items():
        if force or (backbone_name, strategy_name) not in embedded_configs:
            pooled = _cast("_Any", pool_fn)(embeddings).astype(_np.float32)
            _upsert_pooled(con, sid, backbone_name, strategy_name, pooled)

    return True


def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
) -> None:
    """Embed flat pooled representations and persist any missing work."""
    _bootstrap_nomarr()

    from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono
    from nomarr.components.ml.audio.ml_preprocess_comp import preprocess_for_backbone
    from nomarr.components.ml.onnx.ml_session_comp import (
        _BACKBONE_BATCH_SIZE,
        _run_in_batches,
        create_session,
    )

    embedded_configs = _query_embedded_configs(con)
    _PATCHES_DIR.mkdir(parents=True, exist_ok=True)

    _all_paths = _discover_audio()
    audio_paths = (
        [p for p in _all_paths if _song_id(p) in song_ids]
        if song_ids is not None
        else _all_paths
    )
    bb_names = backbones or list(_BACKBONES)

    _log.info("Embedding %d songs × %d backbone(s) ...", len(audio_paths), len(bb_names))

    for bb_name in bb_names:
        bb_cfg = _BACKBONES[bb_name]
        session = create_session(
            bb_cfg["path"],
            device=device,
            vram_limit_bytes=bb_cfg.get("vram_limit_bytes"),
        )
        done = skipped = errors = 0
        t0_ms = _internal_ms().value
        pbar = _tqdm(audio_paths, desc=f"[{bb_name}]", unit="song")
        for path in pbar:
            try:
                worked = _embed_song(
                    path,
                    bb_name,
                    bb_cfg,
                    load_audio_mono,
                    preprocess_for_backbone,
                    session,
                    _run_in_batches,
                    _BACKBONE_BATCH_SIZE,
                    con,
                    embedded_configs,
                    force=force,
                )
                if worked:
                    done += 1
                else:
                    skipped += 1
                pbar.set_postfix(done=done, skip=skipped, err=errors)
            except Exception as exc:
                errors += 1
                _tqdm.write(f"  [ERROR] {bb_name} {path.name}: {exc}")

        elapsed = (_internal_ms().value - t0_ms) / 1000.0
        rate = done / elapsed if elapsed > 0 and done > 0 else 0
        _log.info(
            "[%s] done=%d skipped=%d errors=%d  %.0fs  (%.2f songs/s)",
            bb_name, done, skipped, errors, elapsed, rate,
        )
