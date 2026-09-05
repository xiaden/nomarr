"""Backbone ONNX inference, mask production, and observation-group publication.

Shared by embedding strategies: ``embed`` runs backbone ONNX inference and durably
publishes each per-song stream via digest-only ``StreamStore.publish``, then (mask
production on by default) derives the patch-aligned silence mask and publishes stream
+ mask + commit marker as ONE observation group via ``publish_observation_group``.
This module also owns the CPU-only ``regenerate_masks`` submode, which re-derives masks
over the CURRENT audio with a fingerprint-equality hard refusal (no ONNX on that path).
"""

from __future__ import annotations

import logging as _logging
import time
from typing import TYPE_CHECKING
from typing import Any as _Any

from alive_progress import alive_it as _alive_it

from scripts.embedding_research.config import BACKBONES as _BACKBONES
from scripts.embedding_research.config import bootstrap_nomarr as _bootstrap_nomarr
from scripts.embedding_research.config import discover_audio as _discover_audio
from scripts.embedding_research.config import path_to_meta as _path_to_meta
from scripts.embedding_research.config import song_id as _song_id
from scripts.embedding_research.db import song_exists as _song_exists
from scripts.embedding_research.db import update_corpus_state as _update_corpus_state
from scripts.embedding_research.db import upsert_song as _upsert_song
from scripts.embedding_research.db import write_run_provenance as _write_run_provenance
from scripts.embedding_research.streams import StreamStore
from scripts.embedding_research.streams.masks import canonical_audio_fingerprint as _canonical_audio_fingerprint
from scripts.embedding_research.streams.masks import derive_audio_mask as _derive_audio_mask
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
    produce_masks: bool = False,
) -> bool:
    """
    Compute raw patch embeddings for one song+backbone and durably publish them.

    Returns True if work was done. Skips (returns False) only when the registry already
    holds a verified ``ready`` record for ``(song_id, backbone)`` and ``force=False``
    — a payload file on disk (digest-named, no manifest/ready row) is NOT a skip condition.
    ``force=True`` recomputes and re-publishes an immutable content-addressed replacement:
    the registry re-points at the new digest while bytes at any existing digest are never
    replaced (content-addressed no-replace).

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
    stream_record = store.publish(sid, backbone_name, embeddings, run_id=run_id)
    if produce_masks:
        # Live observation-group publication (P1-S3): derive the patch-aligned silence
        # mask from the SAME canonical waveform the stream was embedded from, then
        # publish stream(already)+mask payload/manifest + commit marker LAST.  Deriving
        # runs the REAL production preprocessing (get_params/compute_log_mel/extract_patches)
        # — no model/session/ONNX on this path.  If the committed group is already
        # present with an identical mask digest, the durable no-replace writer is a no-op.
        audio_fp = _canonical_audio_fingerprint(waveform)
        mask_payload = _derive_audio_mask(
            waveform,
            backbone_name,
            stream_record,
            audio_fingerprint=audio_fp,
        )
        store.publish_observation_group(stream_record, mask_payload)
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
    Plan-C-owned corpus field (``latest_catalog_run_id``) and config hashing remain empty
    here by design (base surface).
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
    produce_masks: bool = True,
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

    _all_paths = _discover_audio()
    audio_paths = [p for p in _all_paths if _song_id(p) in song_ids] if song_ids is not None else _all_paths
    bb_names = backbones or list(_BACKBONES)

    if not bb_names:
        return

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
                    produce_masks=produce_masks,
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


def regenerate_masks(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    backbones: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, int]:
    """CPU-only ``--regenerate-masks`` submode: re-derive masks over the CURRENT audio.

    Explicit CPU-only submode: NO ONNX session/model load/inference is reached anywhere
    on this path (``create_session`` / ``session.run`` are never called).  Each in-scope
    song is decoded via the pinned production loader, its canonical audio fingerprint is
    recomputed, and regeneration is permitted ONLY when that fingerprint EQUALS the
    committed observation group's ``audio_content_sha256``.  A fingerprint mismatch is a
    HARD refusal — a mask may never be written over a different audio file — and there is
    no fallback to a stale mask or a forced re-derive.  Equal fingerprint permits only the
    (idempotent) re-derive + observation-group re-publication; because mask payloads are
    content-addressed, an unchanged waveform reproduces the identical mask digest and the
    durable no-replace writer is a no-op.

    Returns ``{regenerated, skipped, refused, errors}``.  ``skipped`` = songs with no
    committed observation group to regenerate against (nothing to compare); ``refused`` =
    fingerprint mismatch; ``errors`` = decode/derive failures.
    """
    _bootstrap_nomarr()

    from nomarr.components.ml.audio.ml_audio_comp import load_audio_mono

    _all_paths = _discover_audio()
    audio_paths = [p for p in _all_paths if _song_id(p) in song_ids] if song_ids is not None else _all_paths
    bb_names = backbones or list(_BACKBONES)

    store = StreamStore(con)
    tally = {"regenerated": 0, "skipped": 0, "refused": 0, "errors": 0}

    for bb_name in bb_names:
        for path in audio_paths:
            sid = _song_id(path)
            try:
                committed_fp = store.read_committed_mask_audio_fingerprint(sid, bb_name)
                if committed_fp is None:
                    tally["skipped"] += 1
                    continue
                try:
                    waveform = load_audio_mono(str(path), target_sr=16000).waveform
                except Exception as exc:
                    raise RuntimeError(f"Audio load failed: {path}") from exc
                current_fp = _canonical_audio_fingerprint(waveform)
                if current_fp != committed_fp:
                    # HARD refusal: current audio differs from committed group's audio.
                    tally["refused"] += 1
                    _log.error(
                        "%s %s: mask regeneration refused (audio fingerprint changed)",
                        bb_name,
                        path.name,
                    )
                    continue
                stream_record = store.ready_stream_record(sid, bb_name)
                if stream_record is None:
                    tally["skipped"] += 1
                    continue
                mask_payload = _derive_audio_mask(
                    waveform,
                    bb_name,
                    stream_record,
                    audio_fingerprint=current_fp,
                )
                if run_id is not None:
                    from dataclasses import replace

                    mask_payload = replace(mask_payload, run_id=run_id)
                store.publish_observation_group(stream_record, mask_payload)
                tally["regenerated"] += 1
            except Exception as exc:
                tally["errors"] += 1
                _log.error("%s %s: mask regeneration failed: %s", bb_name, path.name, exc)

    return tally
