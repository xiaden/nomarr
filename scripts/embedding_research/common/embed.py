"""Backbone ONNX inference and sidecar writing shared by embedding strategies."""

from __future__ import annotations

import logging as _logging
import time
from typing import TYPE_CHECKING
from typing import Any as _Any

from alive_progress import alive_it as _alive_it

from scripts.embedding_research.config import BACKBONES as _BACKBONES
from scripts.embedding_research.config import PATCHES_DIR as _PATCHES_DIR
from scripts.embedding_research.config import bootstrap_nomarr as _bootstrap_nomarr
from scripts.embedding_research.config import discover_audio as _discover_audio

# Re-exported for common.segment (kept read-only): ``_patches_path``.
from scripts.embedding_research.config import patches_path as _patches_path  # noqa: F401
from scripts.embedding_research.config import path_to_meta as _path_to_meta
from scripts.embedding_research.config import song_id as _song_id
from scripts.embedding_research.db import song_exists as _song_exists
from scripts.embedding_research.db import update_corpus_state as _update_corpus_state
from scripts.embedding_research.db import upsert_song as _upsert_song
from scripts.embedding_research.db import write_run_provenance as _write_run_provenance
from scripts.embedding_research.streams import StreamStore
from scripts.embedding_research.streams.records import now_ms as _now_ms

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
    store: StreamStore,
    run_id: str,
    force: bool,
) -> bool:
    """
    Compute raw patch embeddings for one song+backbone and durably publish them.

    Returns True if work was done. Skips (returns False) only when the registry already
    holds a verified ``ready`` record for ``(song_id, backbone)`` and ``force=False``
    — a bare sidecar file on disk without a ready registry row is NOT a skip condition.
    ``force=True`` recomputes and publishes an immutable replacement (old bytes preserved;
    see the StreamStore immutable-supersession contract).

    Publication goes through the staged durable path (fsync file -> close -> atomic
    rename -> fsync destination directory), then registers a ``pending`` row in one
    transaction with full provenance.  Session must be pre-created by the caller.
    """
    sid = _song_id(path)
    if not force and store.has_ready(sid, backbone_name):
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
    # Durable immutable publication (P2-S1/S2): staged write, fsync/rename/fsync, then a
    # transactional delete-then-insert pending registration pointing at the new artifact.
    store.publish(sid, backbone_name, embeddings, run_id=run_id)
    return True


def _record_embed_run(
    con,
    store: StreamStore,
    run_id: str,
    started_at: int,
    done: int,
    skipped: int,
    errors: int,
    eligible_count: int,
) -> None:
    """End-of-phase completion: reconcile the phase, then record run + corpus state.

    Reconciles the frozen stream store (``pending -> ready`` etc.) and writes exactly one
    ``run_provenance`` row plus the singleton ``corpus_state`` update.  A run with errors
    is recorded ``partial`` (never masquerades as complete).  ``output_artifact_hashes``
    are the published stream fingerprints of this run (the seed of the Plan F manifest).
    Plan-C-owned corpus fields (``latest_catalog_run_id``/``latest_search_view_hash``)
    and config hashing remain empty here by design (base surface).
    """
    report = store.reconcile()
    ready_songs = {rec.song_id for rec in store.ready_rows()}
    output_hashes = ",".join(rec.fingerprint_sha256 for rec in store.run_records(run_id))
    finished_at = _now_ms()
    run_status = "complete" if errors == 0 else "partial"
    _write_run_provenance(
        con,
        run_id=run_id,
        phase="embed",
        status=run_status,
        started_at=started_at,
        finished_at=finished_at,
        output_artifact_hashes=output_hashes,
        song_count=done,
        structural_change_summary=f"done={done}, skipped={skipped}, errors={errors}",
    )
    _update_corpus_state(
        con,
        registered_song_count=len(ready_songs),
        eligible_song_count=eligible_count,
        complete_flag=(errors == 0),
        reconciled_at=finished_at,
        reconciliation_status=(
            "ok"
            if report.clean
            else (
                f"ready={report.ready}, pending={report.pending}, missing={report.missing}, "
                f"corrupt={report.corrupt}, orphan={report.orphan}"
            )
        ),
    )


def embed(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
    backbone_sessions: dict[str, _Any] | None = None,
    run_id: str | None = None,
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

    store = StreamStore(con)
    run_id = run_id or f"embed-{_now_ms()}"
    started_at = _now_ms()

    _log.info("Embedding %d songs x %d backbone(s) ...", len(audio_paths), len(bb_names))

    total_done = total_skipped = total_errors = 0
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
                    store=store,
                    run_id=run_id,
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

        total_done += done
        total_skipped += skipped
        total_errors += errors
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

    # End-of-phase durable completion: reconcile the phase and record run + corpus state.
    _record_embed_run(
        con,
        store,
        run_id,
        started_at,
        total_done,
        total_skipped,
        total_errors,
        len(audio_paths),
    )
