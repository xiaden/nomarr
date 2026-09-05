"""Audio-derived silence masks at the production preprocessing boundary (Plan B P1-S3).

This module is the research-side mask producer.  It INVOKES the shared production
preprocessing functions — ``get_params(backbone)``, ``compute_log_mel(audio, params)``
and ``extract_patches(log_mel, patch_frames, patch_hop)`` from
``nomarr.components.ml.audio.ml_preprocess_comp`` — and does NOT copy framing
constants or accept a second manifest/config input.

Because production ``extract_patches`` returns only the patch array (no starts/slices),
this module MAY use the sole user-approved bounded replay of the frozen production
framing/patch-range arithmetic (``starts = range(0, n_frames - patch_frames + 1,
patch_hop)``) purely to recover the exact start indices / frame slices that the returned
production patch grid represents.  The replay is source-level/golden-equivalent to
production and is always checked against the actually-returned ``log_mel`` frame count
and ``patches`` grid.  It NEVER infers starts from ``patch_index * patch_hop``, adds
geometry/Foley detection, or uses a fallback reader.

The pinned v1 decision (DD § silence-mask semantics) is an Essentia RMS loudness gate:

* ``algorithm = essentia_rms_dbfs_v1``
* ``rms = sqrt(mean(frame^2))`` (Essentia RMS semantics), ``dbfs = 20*log10(max(rms, 1e-12))``
* ``silent_frame = (dbfs <= -60.0)``
* remove isolated silent-frame runs shorter than ``min_silent_run_frames = 2`` before patch reduction
* a patch is initially searchable when >= ``fraction_active_ge = 0.5`` of its covered
  mel frames are non-silent
* apply a two-patch silent-run hysteresis (``min_run_patches = 2``) to the patch decisions
* the mask is ``uint8`` of length exactly ``patch_count`` with ``1 = searchable``.

These defaults are executable configuration, not empirical calibration.  R128's
integrated-loudness gate is NOT used as a per-frame classifier.
"""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass

import numpy as np

from scripts.embedding_research.streams.records import MaskRecord, StreamRecord, now_ms

#: Pinned v1 mask algorithm (executable configuration, not empirical calibration).
MASK_ALGORITHM = "essentia_rms_dbfs_v1"
#: Silence threshold in dBFS (``silent_frame = dbfs <= threshold``).
MASK_THRESHOLD_DBFS = -60.0
#: Isolated silent-frame runs shorter than this many frames are removed pre-reduction.
MIN_SILENT_RUN_FRAMES = 2
#: Isolated silent-patch runs shorter than this many patches are removed (hysteresis).
MIN_RUN_PATCHES = 2
#: A patch is searchable when >= this fraction of its covered mel frames are non-silent.
FRACTION_ACTIVE_GE = 0.5
#: Mask semantics version.
MASK_SEMANTICS_VERSION = "1"
#: Mask payload dtype.
MASK_DTYPE = "uint8"
#: The production preprocessing module invoked for the mask (never copied).
PREPROCESS_FN = "nomarr.components.ml.audio.ml_preprocess_comp"
#: Numeric floor used to keep ``log10`` finite for perfectly silent frames.
_RMS_FLOOR = 1e-12

#: BackbonePreprocessParams framing fields that define params identity.
_PARAMS_ID_FIELDS = (
    "sample_rate",
    "n_mels",
    "n_fft",
    "hop_length",
    "patch_frames",
    "patch_hop",
    "fmin",
    "fmax",
)


def canonical_audio_fingerprint(waveform: np.ndarray) -> str:
    """SHA-256 over the canonical decoded mono float32 samples of *waveform*.

    The audio fingerprint is computed over ``np.ascontiguousarray(waveform,
    dtype=np.float32).tobytes()`` — the canonical decoded mono float32 sample stream.
    Both the stream/mask manifests and any fingerprint-comparison caller (mask
    derivation, ``embed --regenerate-masks``) use exactly this digest, so an equal
    digest is proof the audio content is byte-identical.
    """
    samples = np.ascontiguousarray(waveform, dtype=np.float32).tobytes()
    return hashlib.sha256(samples).hexdigest()


def mask_npy_bytes(mask: np.ndarray) -> bytes:
    """Serialize a uint8 C-order mask array to the exact ``.npy`` payload bytes.

    Masks are ``uint8`` (unlike float32 streams), so this preserves ``np.uint8``
    (``publication.npy_bytes`` is float32-only and is NOT reused here).  Round-trips
    through ``np.load(..., allow_pickle=False)``.
    """
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(mask, dtype=np.uint8))
    return buffer.getvalue()


def replay_patch_starts(n_frames: int, patch_frames: int, patch_hop: int) -> list[int]:
    """Replay the FROZEN production ``extract_patches`` start arithmetic.

    This is the sole approved bounded replay: it reproduces, source-level/golden-
    equivalent, the start positions production ``extract_patches`` computes as
    ``range(0, n_frames - patch_frames + 1, patch_hop)``.  It is used ONLY to recover
    the exact start indices / frame slices that a returned production patch grid
    represents; it is never ``patch_index * patch_hop`` inference and never a second
    preprocessing path.  Callers MUST assert ``len(starts) == patches.shape[0]`` and
    that each patch slice matches the returned grid (the golden-equivalence check).
    """
    if n_frames < patch_frames:
        return []
    return list(range(0, n_frames - patch_frames + 1, patch_hop))


def _params_id(params) -> str:
    """Deterministic params identity from the production framing fields.

    The params come from production ``get_params(backbone)``; hashing the exact
    framing fields (never copying them) gives a stable ``params_id`` for the mask
    manifest without inventing a second config input.
    """
    payload = "|".join(f"{name}={getattr(params, name)}" for name in _PARAMS_ID_FIELDS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _frame_rms(frame: np.ndarray) -> float:
    """Essentia ``RMS`` semantics over one mono frame: ``sqrt(mean(x^2))``."""
    samples = np.asarray(frame, dtype=np.float32)
    return float(math.sqrt(float(np.mean(np.square(samples)))))


def _dbfs(rms: float) -> float:
    """Decibels-full-scale from an RMS amplitude (``20*log10(max(rms, 1e-12))``)."""
    return 20.0 * math.log10(max(rms, _RMS_FLOOR))


def _drop_short_silent_runs(flags: np.ndarray, min_run: int) -> np.ndarray:
    """Turn any run of ``False`` shorter than *min_run* into ``True``.

    Applied identically to mel-frame active flags (``min_silent_run_frames = 2``) and
    to per-patch searchable decisions (``min_run_patches = 2``): a silent run shorter
    than *min_run* is an isolated outlier that must not suppress the surrounding
    active/searchable region.
    """
    out = flags.copy()
    n = flags.size
    i = 0
    while i < n:
        if not flags[i]:
            j = i
            while j < n and not flags[j]:
                j += 1
            if j - i < min_run:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


@dataclass(frozen=True)
class MaskPayload:
    """A derived audio mask plus full provenance, ready for observation-group publication.

    Holds the actual ``uint8`` mask array (so it CANNOT live in the pure
    ``records.py``); :class:`~streams.records.MaskRecord` is the immutable metadata
    record written to the manifest once the payload is on disk.
    """

    song_id: str
    backbone: str
    patch_count: int
    mask: np.ndarray
    algorithm: str = MASK_ALGORITHM
    threshold_dbfs: float = MASK_THRESHOLD_DBFS
    min_silent_run_frames: int = MIN_SILENT_RUN_FRAMES
    hysteresis_frames: int = MIN_RUN_PATCHES
    decision_policy: str = "fraction_active_ge_0.5"
    fraction_active_ge: float = FRACTION_ACTIVE_GE
    mask_semantics_version: str = MASK_SEMANTICS_VERSION
    params_id: str = ""
    audio_content_sha256: str = ""
    preprocess_fn: str = PREPROCESS_FN
    preprocess_version: str = ""
    provenance_source: str = "mask"
    run_id: str = ""
    created_at: int | None = None

    def __post_init__(self) -> None:
        if not self.song_id or "." in self.song_id:
            raise ValueError("mask song_id must be a dot-free token")
        if not self.backbone:
            raise ValueError("mask backbone must be non-empty")
        arr = np.asarray(self.mask)
        if arr.dtype != np.dtype(MASK_DTYPE):
            raise ValueError(f"mask dtype must be {MASK_DTYPE}; got {arr.dtype}")
        if arr.shape != (self.patch_count,):
            raise ValueError(f"mask shape must be ({self.patch_count},); got {arr.shape}")
        if arr.size and not np.isin(arr, (0, 1)).all():
            raise ValueError("mask values must be 0 (silent) or 1 (searchable)")
        if self.patch_count < 1:
            raise ValueError("mask patch_count must be >= 1")
        if not (self.audio_content_sha256 == "" or len(self.audio_content_sha256) == 64):
            raise ValueError("audio_content_sha256 must be a 64-char sha256 hex digest")


def derive_audio_mask(
    audio: np.ndarray,
    backbone: str,
    stream_record: StreamRecord,
    *,
    audio_fingerprint: str,
) -> MaskPayload:
    """Derive a patch-aligned uint8 silence mask from *audio* using PRODUCTION preprocessing.

    Imports ``get_params``/``compute_log_mel``/``extract_patches`` lazily from the
    production module (so sys.modules stubs take effect at call time, exactly as
    ``embed()`` lazily imports preprocess/session).  Calls them with no copied framing
    semantics, then uses the sole approved bounded replay to recover the exact
    starts/slices of the returned production patch grid and applies the pinned RMS /
    hysteresis reduction (DD § mask semantics).

    Hard-fails (raises ``ValueError``) when *audio_fingerprint* does not equal the
    canonical fingerprint of *audio* (a mask may never be written over a different
    audio file) and when the returned production patch count differs from
    *stream_record.patch_count* (patch-count equality is a SUPPLEMENTAL alignment
    consistency check, never alignment proof).

    Zero model/session/ONNX/CUDA access: the only imports are the three production
    preprocessing functions, all applied to the decoded mono waveform.
    """
    # Lazy import so the production module is only resolved at call time.
    from nomarr.components.ml.audio.ml_preprocess_comp import (  # type: ignore[import-not-found]  # lazy production import; research env loads this module standalone (no nomarr visible)
        compute_log_mel,
        extract_patches,
        get_params,
    )

    params = get_params(backbone)
    log_mel = compute_log_mel(audio, params)  # [n_frames, n_mels]
    if log_mel.ndim != 2:
        raise ValueError(f"production compute_log_mel must return [n_frames, n_mels]; got shape {log_mel.shape}")
    n_frames, _n_mels = log_mel.shape

    patches = extract_patches(log_mel, params.patch_frames, params.patch_hop)  # [P, pf, n_mels]
    patch_count = patches.shape[0]

    # Sole approved bounded replay: recover exact starts/slices of the returned grid.
    starts = replay_patch_starts(n_frames, params.patch_frames, params.patch_hop)
    if len(starts) != patch_count:
        raise ValueError(
            f"production extract_patches returned {patch_count} patches but the replayed "
            f"production start grid has {len(starts)} starts (n_frames={n_frames}, "
            f"patch_frames={params.patch_frames}, patch_hop={params.patch_hop}) — replay "
            "no longer matches the returned production grid"
        )
    for p, start in enumerate(starts):
        expected_slice = log_mel[start : start + params.patch_frames]
        if not np.array_equal(patches[p], expected_slice):
            raise ValueError(f"patch {p} does not equal the replayed production frame slice — replay drift")

    # Audio-content fingerprint must match the audio actually handed in.
    actual_fp = canonical_audio_fingerprint(audio)
    if actual_fp != audio_fingerprint:
        raise ValueError(
            f"audio fingerprint mismatch: derived {actual_fp[:12]}… but expected "
            f"{audio_fingerprint[:12]}… (a mask may never be written over a different audio file)"
        )

    # Supplemental patch-count equality with the published stream (never alignment proof).
    if patch_count != stream_record.patch_count:
        raise ValueError(
            f"derived mask patch_count {patch_count} != stream patch_count "
            f"{stream_record.patch_count} for ({stream_record.song_id!r}, "
            f"{stream_record.backbone!r})"
        )

    # One RMS decision per mel-frame of the returned production log_mel grid.
    hop = params.hop_length
    n_fft = params.n_fft
    per_frame_active = np.zeros(n_frames, dtype=bool)
    for i in range(n_frames):
        start = i * hop
        frame = audio[start : start + n_fft]
        rms = _frame_rms(frame)
        silent = _dbfs(rms) <= MASK_THRESHOLD_DBFS
        per_frame_active[i] = not silent

    # Remove isolated silent-frame runs shorter than min_silent_run_frames before reduction.
    per_frame_active = _drop_short_silent_runs(per_frame_active, MIN_SILENT_RUN_FRAMES)

    # Per-patch: searchable when >= fraction_active_ge of covered mel frames are active.
    patch_candidates = np.zeros(patch_count, dtype=bool)
    for p, start in enumerate(starts):
        covered = per_frame_active[start : start + params.patch_frames]
        active_fraction = float(covered.mean())
        patch_candidates[p] = active_fraction >= FRACTION_ACTIVE_GE

    # Two-patch silent-run hysteresis on the patch decisions.
    searchable = _drop_short_silent_runs(patch_candidates, MIN_RUN_PATCHES)
    mask = searchable.astype(np.uint8)

    return MaskPayload(
        song_id=stream_record.song_id,
        backbone=stream_record.backbone,
        patch_count=patch_count,
        mask=mask,
        algorithm=MASK_ALGORITHM,
        threshold_dbfs=MASK_THRESHOLD_DBFS,
        min_silent_run_frames=MIN_SILENT_RUN_FRAMES,
        hysteresis_frames=MIN_RUN_PATCHES,
        fraction_active_ge=FRACTION_ACTIVE_GE,
        mask_semantics_version=MASK_SEMANTICS_VERSION,
        params_id=_params_id(params),
        audio_content_sha256=actual_fp,
        preprocess_fn=PREPROCESS_FN,
        preprocess_version="",
        provenance_source="mask",
        run_id=stream_record.run_id,
        created_at=now_ms(),
    )


def mask_record_from_payload(
    payload: MaskPayload,
    artifact_ref: str,
    mask_sha256: str,
) -> MaskRecord:
    """Build the immutable :class:`MaskRecord` for an on-disk mask payload."""
    return MaskRecord(
        song_id=payload.song_id,
        backbone=payload.backbone,
        artifact_ref=artifact_ref,
        mask_sha256=mask_sha256,
        patch_count=payload.patch_count,
        dimension=1,
        dtype=MASK_DTYPE,
        format_version="1",
        mask_semantics_version=payload.mask_semantics_version,
        algorithm=payload.algorithm,
        threshold_dbfs=payload.threshold_dbfs,
        min_silent_run_frames=payload.min_silent_run_frames,
        hysteresis_frames=payload.hysteresis_frames,
        params_id=payload.params_id,
        audio_content_sha256=payload.audio_content_sha256,
        preprocess_fn=payload.preprocess_fn,
        preprocess_version=payload.preprocess_version,
        provenance_source=payload.provenance_source,
        run_id=payload.run_id,
        created_at=payload.created_at,
        status="pending",
    )


__all__ = [
    "FRACTION_ACTIVE_GE",
    "MASK_ALGORITHM",
    "MASK_DTYPE",
    "MASK_SEMANTICS_VERSION",
    "MASK_THRESHOLD_DBFS",
    "MIN_RUN_PATCHES",
    "MIN_SILENT_RUN_FRAMES",
    "PREPROCESS_FN",
    "MaskPayload",
    "canonical_audio_fingerprint",
    "derive_audio_mask",
    "mask_npy_bytes",
    "mask_record_from_payload",
    "replay_patch_starts",
]
