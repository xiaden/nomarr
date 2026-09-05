"""infer-heads observation writer (Plan B Phase 3, P3-S1/P3-S2).

Runs each CONFIGURED classifier head EXACTLY ONCE over the patch-aligned backbone
observation stream (read from the frozen ``StreamStore``) and publishes ONE complete
digest-named per-song/backbone head-suite artifact
(``heads/{sid}.{backbone}.{64-hex-sha256}.npz``) plus a sibling self-describing
``.json`` manifest through the
:class:`HeadStreamStore` — the ONLY active head-observation writer (Plan E owns CLI wiring).

This mirrors ``common/embed.py``'s writer pattern:

* the module is the observation WRITER; it may load models / create ONNX sessions / run
  ONNX (DD CPU-boundary table R5), but it never re-audio-loads or re-preprocesses — the
  observation sequence is the registered backbone patch stream read via
  ``StreamStore.lookup`` + a full-array ``batch_gather``;
* ONNX head sessions and the batch runner are injected (like embed's ``backbone_sessions``
  seam) so tests run synthetic head outputs with no real models or audio;
* end-of-phase reconcile + one ``run_provenance`` row (phase ``infer-heads``) records the
  outcome via the ``db/provenance.py`` helpers.

Alignment is enforced BEFORE registration (P3-S2).  ``HeadStreamStore.publish`` refuses
— never truncates/pads/recover, and never leaves a row that a later reconcile could
promote to ``ready`` — when any of:

* an expected CONFIGURED head is missing from the produced suite (a partial suite);
* a head's temporal length differs from the backbone stream patch count;
* the backbone stream patch count disagrees with the head suite patch count.

A refused song is recorded (errors/partial run) so no partial/misaligned head stream can
be consumed as ready.
"""

from __future__ import annotations

import logging as _logging
from typing import TYPE_CHECKING

import numpy as np

from scripts.embedding_research.config import BACKBONES as _BACKBONES
from scripts.embedding_research.config import HEAD_VRAM_BYTES as _HEAD_VRAM_BYTES
from scripts.embedding_research.config import HEADS as _HEADS
from scripts.embedding_research.config import bootstrap_nomarr as _bootstrap_nomarr
from scripts.embedding_research.config import discover_audio as _discover_audio
from scripts.embedding_research.config import song_id as _song_id
from scripts.embedding_research.db import write_run_provenance as _write_run_provenance
from scripts.embedding_research.streams import HeadStreamStore, StreamStore
from scripts.embedding_research.streams.records import (
    StreamNotFoundError,
    StreamNotReadyError,
)
from scripts.embedding_research.streams.records import now_ms as _now_ms

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_log = _logging.getLogger(__name__)

#: Names the patch-alignment contract this writer honours (DD ``alignment_version``).
ALIGNMENT_VERSION = "1"

#: The v1 head-suite payload codec version (float32 ``.npz`` per-head arrays).
FORMAT_VERSION = "1"


def _run_head_session(session, embed_batch: np.ndarray) -> np.ndarray:
    """Run one head ONNX session on a single vector or a batch of vectors.

    Heads are softmax classifiers: the session returns ``activations`` and
    ``act[1]`` is the class-1 probability (research contract).  Mirrors the
    classifier head-run helper in ``classify._run_head_session``.
    """
    inp = embed_batch if embed_batch.ndim == 2 else embed_batch[None, :]
    out = session.run(["activations"], {"embeddings": inp.astype(np.float32)})[0]
    return np.asarray(out, dtype=np.float32)


def _run_head_over_patches(session, patches: np.ndarray, run_in_batches_fn, batch_size: int) -> np.ndarray:
    """Run one head over the full patch sequence, returning float32 ``[T, C]``."""
    acts = np.asarray(
        run_in_batches_fn(lambda batch: _run_head_session(session, batch), patches, batch_size),
        dtype=np.float32,
    )
    if acts.ndim != 2:
        raise RuntimeError(f"head session returned {acts.ndim}-D activations; expected [T, C]")
    return acts


def infer_heads_for_song(
    *,
    song_id: str,
    backbone: str,
    backbone_patches: np.ndarray,
    backbone_patch_count: int,
    configured_heads: Iterable[str],
    head_sessions: Mapping[str, object],
    head_store: HeadStreamStore,
    run_id: str,
    force: bool,
    run_in_batches_fn,
    batch_size: int,
    stream_ref: str = "",
    alignment_version: str = ALIGNMENT_VERSION,
    format_version: str = FORMAT_VERSION,
    preprocess_fn: str = "",
    preprocess_version: str = "",
    backbone_model_hash: str = "",
) -> bool:
    """Run every configured head once over one song/backbone stream and publish the suite.

    Returns True when a suite was published.  Skips (returns False) only when the head
    registry already holds a verified ``ready`` record for ``(song_id, backbone)`` and
    ``force=False``.  ``backbone_patches`` is the full patch-aligned observation read from
    the backbone stream and ``backbone_patch_count`` its registered patch count (the
    alignment source of truth).  ``configured_heads`` is the CONFIGURED head set for the
    backbone and ``head_sessions`` maps each head name to its ONNX session.

    *stream_ref* is the root-relative ``artifact_ref`` of the committed backbone stream the
    suite is aligned to (threaded from ``infer_heads()``'s ``stream_store.lookup``).  It is
    recorded in the published head manifest as stream-alignment provenance.  Default ``""``
    keeps direct callers unchanged (manifest records no committed-stream provenance).

    Alignment/refusal (P3-S2) is delegated to :meth:`HeadStreamStore.publish`, which runs
    BEFORE any registry row is written: it refuses (raising) a partial suite, a head whose
    temporal length differs from ``backbone_patch_count``, or non-finite arrays — so a
    misaligned suite can never be registered ``pending`` and later reconciled ``ready``.
    """
    if not force and head_store.has_ready(song_id, backbone):
        return False

    heads = sorted(configured_heads)
    if not heads:
        raise RuntimeError(f"no configured heads for backbone {backbone!r}; cannot publish an empty head suite")
    missing_sessions = [head for head in heads if head not in head_sessions]
    if missing_sessions:
        raise RuntimeError(
            f"backbone {backbone!r} has configured head(s) {missing_sessions} with no session; "
            "the head suite would be incomplete and is refused"
        )

    patches = np.asarray(backbone_patches, dtype=np.float32)
    if patches.ndim != 2:
        raise ValueError(f"backbone_patches must be 2-D [T, dim]; got shape {patches.shape}")
    if patches.shape[0] != backbone_patch_count:
        raise ValueError(
            f"backbone stream patch count {backbone_patch_count} disagrees with gathered patch rows "
            f"{patches.shape[0]}; misaligned head run refused"
        )

    # Run each configured head EXACTLY ONCE over the whole patch-aligned sequence.
    head_arrays: dict[str, np.ndarray] = {}
    for head in heads:
        head_arrays[head] = _run_head_over_patches(head_sessions[head], patches, run_in_batches_fn, batch_size)

    head_store.publish(
        song_id,
        backbone,
        head_arrays,
        run_id=run_id,
        patch_count=backbone_patch_count,
        alignment_version=alignment_version,
        expected_head_ids=heads,
        format_version=format_version,
        preprocess_fn=preprocess_fn,
        preprocess_version=preprocess_version,
        backbone_model_hash=backbone_model_hash,
        stream_ref=stream_ref,
    )
    return True


def _record_infer_heads_run(
    con,
    head_store: HeadStreamStore,
    run_id: str,
    started_at: int,
    done: int,
    skipped: int,
    errors: int,
) -> None:
    """End-of-phase completion: reconcile the head registry, then record the run.

    Reconciles the head stream store (``pending -> ready``) and writes exactly one
    ``run_provenance`` row for the ``infer-heads`` phase.  A run with refusals/errors is
    recorded ``partial`` (never masquerades as complete).  ``output_artifact_hashes`` are
    the published head-suite fingerprints of this run.
    """
    head_store.reconcile()
    output_hashes = ",".join(rec.fingerprint_sha256 for rec in head_store.run_records(run_id))
    _write_run_provenance(
        con,
        run_id=run_id,
        phase="infer-heads",
        status="complete" if errors == 0 else "partial",
        started_at=started_at,
        finished_at=_now_ms(),
        output_artifact_hashes=output_hashes,
        song_count=done,
        structural_change_summary=f"done={done}, skipped={skipped}, errors={errors}",
    )


def infer_heads(
    con,
    *,
    song_ids: frozenset[str] | None = None,
    force: bool = False,
    backbones: list[str] | None = None,
    device: str = "cpu",
    head_sessions: dict[str, dict[str, object]] | None = None,
    run_id: str | None = None,
    run_in_batches_fn=None,
    batch_size: int | None = None,
) -> None:
    """Run infer-heads for each in-scope song/backbone with a verified backbone stream.

    If *head_sessions* is provided the sessions are used as-is and ``create_session`` is
    not called (caller owns their lifetime); otherwise sessions are created per configured
    head.  A song/backbone is processed only when its backbone patch stream is registered
    and ``ready`` (heads cannot be aligned without it).  End-of-phase reconciles the head
    registry and records the run.
    """
    _bootstrap_nomarr()

    from nomarr.components.ml.onnx.ml_session_comp import _BACKBONE_BATCH_SIZE, _run_in_batches, create_session

    effective_run_batches = run_in_batches_fn or _run_in_batches
    effective_batch_size = batch_size if batch_size is not None else _BACKBONE_BATCH_SIZE

    stream_store = StreamStore(con)
    head_store = HeadStreamStore(con)
    run_id = run_id or f"infer-heads-{_now_ms()}"
    started_at = _now_ms()

    all_paths = _discover_audio()
    audio_paths = [p for p in all_paths if _song_id(p) in song_ids] if song_ids is not None else all_paths
    bb_names = backbones or list(_BACKBONES)

    total_done = total_skipped = total_errors = 0
    for backbone in bb_names:
        configured = sorted(_HEADS.get(backbone, {}))
        if not configured:
            _log.warning("[%s] no configured heads — skipping infer-heads for this backbone", backbone)
            continue

        # Resolve per-head sessions once for this backbone.
        sessions_for_backbone: dict[str, object] = {}
        for head in configured:
            if head_sessions is not None:
                cached = head_sessions.get(backbone, {}).get(head)
                if cached is None:
                    _log.error("[%s/%s] head session not found in pre-loaded cache — skipping head", backbone, head)
                    continue
                sessions_for_backbone[head] = cached
            else:
                sessions_for_backbone[head] = create_session(
                    _HEADS[backbone][head], device=device, vram_limit_bytes=_HEAD_VRAM_BYTES
                )

        done = skipped = errors = 0
        for path in audio_paths:
            sid = _song_id(path)
            try:
                stream_record = stream_store.lookup(sid, backbone)
            except (StreamNotFoundError, StreamNotReadyError):
                skipped += 1
                continue
            try:
                patches = stream_store.batch_gather(sid, backbone, list(range(stream_record.patch_count)))
            except Exception as exc:
                errors += 1
                _log.error("[%s/%s] %s failed to gather backbone stream: %s", backbone, sid, path.name, exc)
                continue
            try:
                worked = infer_heads_for_song(
                    song_id=sid,
                    backbone=backbone,
                    backbone_patches=patches,
                    backbone_patch_count=stream_record.patch_count,
                    configured_heads=configured,
                    head_sessions=sessions_for_backbone,
                    head_store=head_store,
                    run_id=run_id,
                    force=force,
                    run_in_batches_fn=effective_run_batches,
                    batch_size=effective_batch_size,
                    stream_ref=stream_record.artifact_ref,
                )
                if worked:
                    done += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors += 1
                _log.error("[%s/%s] %s head inference refused: %s", backbone, sid, path.name, exc)

        _log.info("[%s] infer-heads done=%d skipped=%d errors=%d", backbone, done, skipped, errors)
        total_done += done
        total_skipped += skipped
        total_errors += errors

    _record_infer_heads_run(con, head_store, run_id, started_at, total_done, total_skipped, total_errors)
