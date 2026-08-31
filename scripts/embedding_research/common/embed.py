"""Backbone ONNX inference and sidecar writing shared by embedding strategies."""

from __future__ import annotations

import logging as _logging
import time
from typing import TYPE_CHECKING
from typing import Any as _Any

import numpy as _np
from alive_progress import alive_it as _alive_it

from scripts.embedding_research.config import BACKBONES as _BACKBONES
from scripts.embedding_research.config import PATCHES_DIR as _PATCHES_DIR
from scripts.embedding_research.config import bootstrap_nomarr as _bootstrap_nomarr
from scripts.embedding_research.config import discover_audio as _discover_audio
from scripts.embedding_research.config import patches_path as _patches_path
from scripts.embedding_research.config import path_to_meta as _path_to_meta
from scripts.embedding_research.config import song_id as _song_id
from scripts.embedding_research.db import song_exists as _song_exists
from scripts.embedding_research.db import upsert_song as _upsert_song

if TYPE_CHECKING:
    from pathlib import Path as _Path

_log = _logging.getLogger(__name__)


def _embed_song_raw(
    path: _Path,
    backbone_name: str,
    backbone_cfg: dict[str, _Any],
    load_audio_fn,
    preprocess_fn,
    session,
    run_in_batches_fn,
    batch_size: int,
    con,
    *,
    force: bool,
) -> bool:
    """
    Compute raw patch embeddings for one song+backbone and save the sidecar.
    Returns True if work was done. Skips when the sidecar already exists unless
    force=True. Session must be pre-created by the caller (created once per
    backbone, not per song).
    """
    sid = _song_id(path)
    sidecar = _patches_path(sid, backbone_name)
    if sidecar.exists() and not force:
        return False

    if not _song_exists(con, sid):
        meta = _path_to_meta(path)
        _upsert_song(
            con,
            sid,
            meta["path"],
            meta["artist"],
            meta["album"],
            meta["title"],
            meta.get("genre", "unknown"),
        )

    try:
        result = load_audio_fn(str(path), target_sr=16000)
        waveform = result.waveform
    except Exception as exc:
        raise RuntimeError(f"Audio load failed: {path}") from exc

    patches = preprocess_fn(waveform, backbone_cfg["backbone_name"])
    if patches is None or len(patches) == 0:
        return False

    def _predict(batch):
        return session.run(["embeddings"], {"melspectrogram": batch})[0]

    embeddings = run_in_batches_fn(_predict, patches, batch_size)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    _np.save(str(sidecar), embeddings.astype(_np.float32))
    return True


def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
    backbone_sessions: dict[str, _Any] | None = None,
) -> None:
    """Run backbone ONNX inference for each in-scope song and backbone.

    If *backbone_sessions* is provided the sessions are used as-is and
    ``create_session`` is not called; caller is responsible for their lifetime.
    """
    _bootstrap_nomarr()

    from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono
    from nomarr.components.ml.audio.ml_preprocess_comp import preprocess_for_backbone
    from nomarr.components.ml.onnx.ml_session_comp import (
        _BACKBONE_BATCH_SIZE,
        _run_in_batches,
        create_session,
    )

    _PATCHES_DIR.mkdir(parents=True, exist_ok=True)

    _all_paths = _discover_audio()
    audio_paths = [p for p in _all_paths if _song_id(p) in song_ids] if song_ids is not None else _all_paths
    bb_names = backbones or list(_BACKBONES)

    _log.info("Embedding %d songs x %d backbone(s) ...", len(audio_paths), len(bb_names))

    for bb_name in bb_names:
        bb_cfg = _BACKBONES[bb_name]
        if backbone_sessions is not None:
            if bb_name not in backbone_sessions:
                _log.error("[%s] backbone session not found in pre-loaded cache — skipping", bb_name)
                continue
            session = backbone_sessions[bb_name]
        else:
            session = create_session(
                bb_cfg["path"],
                device=device,
                vram_limit_bytes=bb_cfg.get("vram_limit_bytes"),
            )
        done = skipped = errors = 0
        t0 = time.perf_counter()
        pbar = _alive_it(audio_paths, title=f"[{bb_name}]")
        for path in pbar:
            try:
                worked = _embed_song_raw(
                    path,
                    bb_name,
                    bb_cfg,
                    load_audio_mono,
                    preprocess_for_backbone,
                    session,
                    _run_in_batches,
                    _BACKBONE_BATCH_SIZE,
                    con,
                    force=force,
                )
                if worked:
                    done += 1
                else:
                    skipped += 1
                pbar.text(f"done={done} skip={skipped} err={errors}")
            except Exception as exc:
                errors += 1
                _log.error("%s %s: %s", bb_name, path.name, exc)

        elapsed = time.perf_counter() - t0
        rate = done / elapsed if elapsed > 0 and done > 0 else 0
        _log.info(
            "[%s] done=%d skipped=%d errors=%d  %.0fs  (%.2f songs/s)",
            bb_name,
            done,
            skipped,
            errors,
            elapsed,
            rate,
        )
