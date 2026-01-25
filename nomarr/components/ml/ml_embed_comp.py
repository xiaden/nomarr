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
from nomarr.helpers.dto.ml_dto import SegmentWaveformParams


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
    params: SegmentWaveformParams,
) -> Segments:
    """
    Slice a mono waveform into overlapping fixed-length segments.

    Args:
        params: SegmentWaveformParams with:
            - y: Waveform array
            - sr: Sample rate
            - segment_s: Window length in seconds
            - hop_s: Hop length in seconds
            - pad_final: If True, zero-pad the last short segment to full length
    """
    waveform = params.y
    sr = params.sr
    segment_s = params.segment_s
    hop_s = params.hop_s
    pad_final = params.pad_final

    if segment_s <= 0 or hop_s <= 0:
        raise ValueError("segment_s and hop_s must be > 0")

    seg_len = round(segment_s * sr)
    hop_len = round(hop_s * sr)
    if seg_len <= 0 or hop_len <= 0:
        raise ValueError("segment length/hop too small for given sr")

    waves: list[np.ndarray] = []
    bounds: list[tuple[float, float]] = []

    num_samples = len(waveform)
    if num_samples == 0:
        return Segments(waves, bounds, sr)

    start = 0
    while start < num_samples:
        end = start + seg_len
        if end <= num_samples:
            seg = waveform[start:end]
        else:
            # last partial
            if not pad_final:
                seg = waveform[start:num_samples]
                if len(seg) == 0:
                    break
            else:
                seg = np.zeros(seg_len, dtype=np.float32)
                remain = waveform[start:num_samples]
                seg[: len(remain)] = remain
                end = num_samples  # logical end at file end

        t0 = start / sr
        t1 = min(end, num_samples) / sr
        waves.append(np.asarray(seg, dtype=np.float32))
        bounds.append((t0, t1))

        # Advance
        if start + hop_len >= num_samples:
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
    dim = max(output.shape[0] for output in outputs)
    padded = []
    for output in outputs:
        if output.shape[0] == dim:
            padded.append(output)
        else:
            # rare: if a backend returns inconsistent dims across segments, pad with NaN then handle in pooling
            tmp = np.full((dim,), np.nan, dtype=np.float32)
            tmp[: min(dim, output.shape[0])] = output[: min(dim, output.shape[0])]
            padded.append(tmp)
    return np.vstack(padded)


# ----------------------------------------------------------------------
# Pooling
# ----------------------------------------------------------------------
def pool_scores(
    scores: np.ndarray,
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
    if scores.size == 0:
        return scores

    if nan_policy == "omit":
        # mask NaNs per-dimension
        mask = ~np.isnan(scores)
        # fallback: if a column is all NaN, set mask to zeros; we'll replace later
        col_all_nan = (~mask).all(axis=0)

        if mode == "mean":
            pooled = np.where(
                col_all_nan,
                0.0,
                np.nanmean(scores, axis=0),
            )
        elif mode == "median":
            pooled = np.where(
                col_all_nan,
                0.0,
                np.nanmedian(scores, axis=0),
            )
        elif mode == "trimmed_mean":
            pooled = _trimmed_mean(scores, trim_perc, axis=0)
            pooled = np.where(
                col_all_nan,
                0.0,
                pooled,
            )
        else:
            raise ValueError(f"Unknown pooling mode: {mode}")
        return pooled.astype(np.float32, copy=False)

    # nan_policy == "propagate"  # noqa: E800
    if mode == "mean":
        result: np.ndarray = np.mean(scores, axis=0).astype(np.float32, copy=False)
        return result
    if mode == "median":
        result = np.median(scores, axis=0).astype(np.float32, copy=False)
        return result
    if mode == "trimmed_mean":
        return _trimmed_mean(scores, trim_perc, axis=0).astype(np.float32, copy=False)
    raise ValueError(f"Unknown pooling mode: {mode}")


def _trimmed_mean(scores: np.ndarray, trim_perc: float, axis: int = 0) -> np.ndarray:
    """
    Compute a symmetric trimmed mean along axis, ignoring NaNs.
    Example: trim_perc=0.1 drops lowest 10% and highest 10% per dimension.
    """
    if not (0.0 <= trim_perc < 0.5):
        raise ValueError("trim_perc must be in [0, 0.5)")

    # Work column-wise to support NaN-robust behavior
    if axis != 0:
        scores = np.swapaxes(scores, axis, 0)

    num_rows = scores.shape[0]
    trim_count = int(np.floor(trim_perc * num_rows))
    if num_rows == 0:
        return np.array([], dtype=np.float32)

    result = np.zeros((scores.shape[1],), dtype=np.float32)
    for col_idx in range(scores.shape[1]):
        col = scores[:, col_idx]
        col = col[~np.isnan(col)]
        if col.size == 0:
            result[j] = 0.0
            continue
        col.sort()
        lo = trim_count
        hi = max(trim_count, col.size - trim_count)
        trimmed = col[lo:hi] if hi > lo else col
        result[j] = float(np.mean(trimmed)) if trimmed.size else 0.0

    if axis != 0:
        result = np.swapaxes(result, axis, 0)
    return result
