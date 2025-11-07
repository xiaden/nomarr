#!/usr/bin/env python3
# ======================================================================
#  Essentia Autotag - Embedding & Segmentation Utilities (fixed)
#  Inference-agnostic helpers: load audio, segment, score, pool.
#  (Essentia TF graph wiring happens in processor.py)
# ======================================================================

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

# Local modules
from nomarr.helpers.audio import load_audio_mono, should_skip_short


# ----------------------------------------------------------------------
# Segmentation
# ----------------------------------------------------------------------
@dataclass
class Segments:
    """Holds segmented waveform and boundaries in seconds (start, end)."""

    waves: list[np.ndarray]
    bounds: list[tuple[float, float]]  # (start_s, end_s)
    sr: int


def segment_waveform(
    y: np.ndarray,
    sr: int,
    segment_s: float = 10.0,
    hop_s: float = 5.0,
    pad_final: bool = False,
) -> Segments:
    """
    Slice a mono waveform into overlapping fixed-length segments.
    - segment_s: window length in seconds
    - hop_s: hop length in seconds
    - pad_final: if True, zero-pad the last short segment to full length
    """
    if segment_s <= 0 or hop_s <= 0:
        raise ValueError("segment_s and hop_s must be > 0")

    seg_len = round(segment_s * sr)
    hop_len = round(hop_s * sr)
    if seg_len <= 0 or hop_len <= 0:
        raise ValueError("segment length/hop too small for given sr")

    waves: list[np.ndarray] = []
    bounds: list[tuple[float, float]] = []

    n = len(y)
    if n == 0:
        return Segments(waves, bounds, sr)

    start = 0
    while start < n:
        end = start + seg_len
        if end <= n:
            seg = y[start:end]
        else:
            # last partial
            if not pad_final:
                seg = y[start:n]
                if len(seg) == 0:
                    break
            else:
                seg = np.zeros(seg_len, dtype=np.float32)
                remain = y[start:n]
                seg[: len(remain)] = remain
                end = n  # logical end at file end

        t0 = start / sr
        t1 = min(end, n) / sr
        waves.append(np.asarray(seg, dtype=np.float32))
        bounds.append((t0, t1))

        # Advance
        if start + hop_len >= n:
            break
        start += hop_len

    return Segments(waves=waves, bounds=bounds, sr=sr)


# ----------------------------------------------------------------------
# Scoring over segments
# ----------------------------------------------------------------------
def score_segments(
    segments: Segments,
    predict_fn: Callable[[np.ndarray, int], np.ndarray],
) -> np.ndarray:
    """
    Apply predict_fn to each segment waveform.
    predict_fn signature: (wave_mono_float32, sr) -> 1D np.ndarray (scores/logits/probs)
    Returns a 2D array: (num_segments, dim)
    """
    outputs: list[np.ndarray] = []
    for seg in segments.waves:
        out = predict_fn(seg, segments.sr)
        out = np.asarray(out).reshape(-1).astype(np.float32, copy=False)
        outputs.append(out)
    if not outputs:
        return np.zeros((0, 0), dtype=np.float32)
    # Validate consistent dimension
    dim = max(o.shape[0] for o in outputs)
    padded = []
    for o in outputs:
        if o.shape[0] == dim:
            padded.append(o)
        else:
            # rare: if a backend returns inconsistent dims across segments, pad with NaN then handle in pooling
            tmp = np.full((dim,), np.nan, dtype=np.float32)
            tmp[: min(dim, o.shape[0])] = o[: min(dim, o.shape[0])]
            padded.append(tmp)
    return np.vstack(padded)


# ----------------------------------------------------------------------
# Pooling
# ----------------------------------------------------------------------
def pool_scores(
    S: np.ndarray,
    mode: str = "mean",
    *,
    trim_perc: float = 0.1,
    nan_policy: str = "omit",
) -> np.ndarray:
    """
    Pool segment-level scores into a single vector.
    - mode: "mean", "median", or "trimmed_mean"
    - trim_perc: for trimmed_mean, fraction to drop from each tail (0..0.4 recommended)
    - nan_policy: "omit" (ignore NaNs) or "propagate"
    """
    if S.size == 0:
        return S

    if nan_policy == "omit":
        # mask NaNs per-dimension
        mask = ~np.isnan(S)
        # fallback: if a column is all NaN, set mask to zeros; we'll replace later
        col_all_nan = (~mask).all(axis=0)

        if mode == "mean":
            pooled = np.where(
                col_all_nan,
                0.0,
                np.nanmean(S, axis=0),
            )
        elif mode == "median":
            pooled = np.where(
                col_all_nan,
                0.0,
                np.nanmedian(S, axis=0),
            )
        elif mode == "trimmed_mean":
            pooled = _trimmed_mean(S, trim_perc, axis=0)
            pooled = np.where(
                col_all_nan,
                0.0,
                pooled,
            )
        else:
            raise ValueError(f"Unknown pooling mode: {mode}")
        return pooled.astype(np.float32, copy=False)

    # nan_policy == "propagate"
    if mode == "mean":
        return np.mean(S, axis=0).astype(np.float32, copy=False)
    if mode == "median":
        return np.median(S, axis=0).astype(np.float32, copy=False)
    if mode == "trimmed_mean":
        return _trimmed_mean(S, trim_perc, axis=0).astype(np.float32, copy=False)
    raise ValueError(f"Unknown pooling mode: {mode}")


def _trimmed_mean(S: np.ndarray, trim_perc: float, axis: int = 0) -> np.ndarray:
    """
    Compute a symmetric trimmed mean along axis, ignoring NaNs.
    Example: trim_perc=0.1 drops lowest 10% and highest 10% per dimension.
    """
    if not (0.0 <= trim_perc < 0.5):
        raise ValueError("trim_perc must be in [0, 0.5)")

    # Work column-wise to support NaN-robust behavior
    if axis != 0:
        S = np.swapaxes(S, axis, 0)

    n = S.shape[0]
    k = int(np.floor(trim_perc * n))
    if n == 0:
        return np.array([], dtype=np.float32)

    result = np.zeros((S.shape[1],), dtype=np.float32)
    for j in range(S.shape[1]):
        col = S[:, j]
        col = col[~np.isnan(col)]
        if col.size == 0:
            result[j] = 0.0
            continue
        col.sort()
        lo = k
        hi = max(k, col.size - k)
        trimmed = col[lo:hi] if hi > lo else col
        result[j] = float(np.mean(trimmed)) if trimmed.size else 0.0

    if axis != 0:
        result = np.swapaxes(result, axis, 0)
    return result


# ----------------------------------------------------------------------
# High-level convenience: end-to-end scoring with guards
# ----------------------------------------------------------------------
def analyze_with_segments(
    path: str,
    *,
    target_sr: int,
    segment_s: float,
    hop_s: float,
    min_duration_s: int,
    allow_short: bool,
    predict_fn: Callable[[np.ndarray, int], np.ndarray],
    pool: str = "trimmed_mean",
    trim_perc: float = 0.1,
) -> tuple[np.ndarray, Segments, float]:
    """
    Full flow for a single backbone/head:
      1) load mono audio at target_sr
      2) duration gating (skip short if not allowed)
      3) segment
      4) run predict_fn over segments → per-segment vectors
      5) pool across segments

    Returns:
      pooled_vector, segments_info, duration_seconds

    Raises:
      RuntimeError with a clear message when skipping due to short audio.
    """
    import logging
    import time

    t0 = time.time()
    y, sr, duration = load_audio_mono(path, target_sr=target_sr)
    logging.debug(f"[embed] Audio loaded in {time.time() - t0:.2f}s ({duration:.1f}s duration)")

    # FIX: correctly pass allow_short into should_skip_short
    if should_skip_short(duration, min_duration_s, allow_short):
        raise RuntimeError(f"audio too short ({duration:.2f}s < {min_duration_s}s)")

    t1 = time.time()
    segs = segment_waveform(y, sr, segment_s=segment_s, hop_s=hop_s, pad_final=True)
    logging.debug(f"[embed] Segmented into {len(segs.waves)} segments in {time.time() - t1:.2f}s")
    if len(segs.waves) == 0:
        raise RuntimeError("no segments produced (possibly empty or invalid audio)")

    t2 = time.time()
    S = score_segments(segs, predict_fn)  # (num_segments, dim)
    logging.debug(f"[embed] Scored {len(segs.waves)} segments in {time.time() - t2:.2f}s")
    if S.size == 0:
        raise RuntimeError("predictor returned empty scores")

    pooled = pool_scores(S, mode=pool, trim_perc=trim_perc, nan_policy="omit")
    logging.debug(f"[embed] Total analyze time: {time.time() - t0:.2f}s")
    return pooled, segs, duration
