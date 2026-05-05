#!/usr/bin/env python3
# ======================================================================
#  Nomarr - Embedding & Segmentation Utilities (fixed)
#  Inference-agnostic helpers: load audio, segment, score, pool.
#  (Essentia TF graph wiring happens in processor.py)
# ======================================================================

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.ndimage import uniform_filter1d

# Local modules

if TYPE_CHECKING:
    from collections.abc import Callable

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


def segment_waveform(params: SegmentWaveformParams) -> Segments:
    """Slice a mono waveform into overlapping fixed-length segments.

    Args:
        params: SegmentWaveformParams with:
            - y: Waveform array
            - sr: Sample rate
            - segment_s: Window length in seconds
            - hop_s: Hop length in seconds
            - pad_final: If True, zero-pad the last short segment to full length

    """
    waveform = params.waveform
    sr = params.sr
    segment_s = params.segment_s
    hop_s = params.hop_s
    pad_final = params.pad_final

    if segment_s <= 0 or hop_s <= 0:
        msg = "segment_s and hop_s must be > 0"
        raise ValueError(msg)

    seg_len = round(segment_s * sr)
    hop_len = round(hop_s * sr)
    if seg_len <= 0 or hop_len <= 0:
        msg = "segment length/hop too small for given sr"
        raise ValueError(msg)

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
        # last partial
        elif not pad_final:
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
def score_segments(segments: Segments, predict_fn: Callable[[np.ndarray, int], np.ndarray]) -> np.ndarray:
    """Apply predict_fn to each segment waveform.
    predict_fn signature: (wave_mono_float32, sr) -> 1D np.ndarray (scores/logits/probs)
    Returns a 2D array: (num_segments, dim).
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
    """Pool segment-level scores into a single vector.
    - mode: "mean", "median", or "trimmed_mean"
    - trim_perc: for trimmed_mean, fraction to drop from each tail (0..0.4 recommended)
    - nan_policy: "omit" (ignore NaNs) or "propagate".
    """
    if scores.size == 0:
        return scores

    if nan_policy == "omit":
        # mask NaNs per-dimension
        mask = ~np.isnan(scores)
        # fallback: if a column is all NaN, set mask to zeros; we'll replace later
        col_all_nan = (~mask).all(axis=0)

        if mode == "mean":
            pooled = np.where(col_all_nan, 0.0, np.nanmean(scores, axis=0))
        elif mode == "median":
            pooled = np.where(col_all_nan, 0.0, np.nanmedian(scores, axis=0))
        elif mode == "trimmed_mean":
            pooled = _trimmed_mean(scores, trim_perc, axis=0)
            pooled = np.where(col_all_nan, 0.0, pooled)
        else:
            msg = f"Unknown pooling mode: {mode}"
            raise ValueError(msg)
        return pooled.astype(np.float32, copy=False)

    # nan_policy == "propagate"
    if mode == "mean":
        result: np.ndarray = np.mean(scores, axis=0).astype(np.float32, copy=False)
        return result
    if mode == "median":
        median_result: np.ndarray = np.median(scores, axis=0).astype(np.float32, copy=False)
        return median_result
    if mode == "trimmed_mean":
        return _trimmed_mean(scores, trim_perc, axis=0).astype(np.float32, copy=False)
    msg = f"Unknown pooling mode: {mode}"
    raise ValueError(msg)


def _trimmed_mean(scores: np.ndarray, trim_perc: float, axis: int = 0) -> np.ndarray:
    """Compute a symmetric trimmed mean along axis, ignoring NaNs.
    Example: trim_perc=0.1 drops lowest 10% and highest 10% per dimension.
    """
    if not (0.0 <= trim_perc < 0.5):
        msg = "trim_perc must be in [0, 0.5)"
        raise ValueError(msg)

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
            result[col_idx] = 0.0
            continue
        col.sort()
        lo = trim_count
        hi = max(trim_count, col.size - trim_count)
        trimmed = col[lo:hi] if hi > lo else col
        result[col_idx] = float(np.mean(trimmed)) if trimmed.size else 0.0

    if axis != 0:
        result = np.swapaxes(result, axis, 0)
    return result


def aggregate_segment_scores_weighted(
    scores: np.ndarray,
    *,
    silence_threshold: float = 0.05,
    min_active_fraction: float = 0.3,
    rolling_window: int = 3,
    group_change_threshold: float = 0.10,
    oscillation_fraction: float = 0.45,
) -> np.ndarray:
    """Aggregate segment-level classification head scores using temporal grouping.

    More robust than a plain trimmed mean for binary / multiclass heads.
    Inputs are assumed to be probabilities in ``[0, 1]``.

    Steps:

    1. **Silence filtering** — segments whose max probability is below
       *silence_threshold* are excluded before grouping.  If silence
       filtering would leave fewer than *min_active_fraction* of the
       original segments, all segments are retained as a fallback.
    2. **Rolling average** — a centred rolling mean with window
       *rolling_window* is applied to each label independently to
       smooth short-term fluctuation.
    3. **Temporal grouping** — consecutive segments are placed in the
       same group while the L-infinity distance between adjacent rolling-average
       vectors is <= *group_change_threshold*.  A larger jump opens a new
       group, splitting the track into structurally similar sections.
    4. **Weighted aggregation** — each group is assigned a weight equal
       to its segment count.  For each label separately, the groups are
       split into a "yes" side (mean > 0.5) and a "no" side (mean ≤ 0.5).
       The weighted mean of the *dominant* side (greater total weight) is
       used as the label's song score.
    5. **Oscillation suppression** — when neither side carries at least
       ``1 - oscillation_fraction`` of the total weight (i.e. the model
       is constantly switching), the label score is clamped to the
       decision midpoint (0.5), effectively suppressing the tag.

    Falls back to a 10 % trimmed mean when fewer than 2 active segments
    remain after silence filtering.

    Args:
        scores: 2-D array of shape ``[num_segments, num_labels]``.
            Values must be in probability space ``[0, 1]``.
        silence_threshold: Segments whose ``max(score)`` across labels is
            below this value are considered silent and excluded.
        min_active_fraction: Minimum fraction of the original segments
            that must remain after silence filtering.  If fewer survive,
            all segments are kept.
        rolling_window: Centred window width for the temporal smoothing
            step.  Automatically capped at the number of active segments.
        group_change_threshold: Maximum L-infinity distance between adjacent
            rolling-average vectors before a new group is started.
        oscillation_fraction: A label is considered oscillating when the
            *smaller* of the two probability sides carries at least this
            fraction of total group weight.  Oscillating labels are
            suppressed to 0.5.

    Returns:
        1-D ``float32`` array of shape ``[num_labels]``.

    """
    if scores.ndim == 1:
        scores = scores.reshape(1, -1)
    n_segs, n_labels = scores.shape
    if n_segs <= 1:
        return scores.reshape(-1).astype(np.float32, copy=False)

    # Step 1: silence filtering
    activity = np.max(scores, axis=1)
    active_mask = activity >= silence_threshold
    min_active = max(1, int(np.floor(min_active_fraction * n_segs)))
    if int(np.sum(active_mask)) < min_active:
        active_mask = np.ones(n_segs, dtype=bool)
    active_scores: np.ndarray = scores[active_mask]
    n_active = len(active_scores)

    if n_active <= 1:
        # Not enough active segments — fall back to trimmed mean over all
        return _trimmed_mean(scores, 0.1, axis=0).astype(np.float32, copy=False)

    # Step 2: centred rolling average (vectorized via scipy uniform filter)
    w = min(rolling_window, n_active)
    rolled = uniform_filter1d(
        active_scores.astype(np.float64),
        size=w,
        axis=0,
        mode="nearest",
    ).astype(np.float32, copy=False)

    # Step 3: group detection — split on L-inf deviation in rolling average
    groups: list[list[int]] = []
    current_group: list[int] = [0]
    for i in range(1, n_active):
        linf_dist = float(np.max(np.abs(rolled[i] - rolled[i - 1])))
        if linf_dist <= group_change_threshold:
            current_group.append(i)
        else:
            groups.append(current_group)
            current_group = [i]
    groups.append(current_group)

    # Step 4: per-group means and weights (normalised to sum to 1)
    group_means = np.array(
        [np.mean(active_scores[g], axis=0) for g in groups],
        dtype=np.float32,
    )
    raw_weights = np.array([float(len(g)) for g in groups], dtype=np.float64)
    group_weights = raw_weights / raw_weights.sum()

    # Step 5 + oscillation suppression: per-label dominant-side selection
    pooled = np.empty(n_labels, dtype=np.float32)
    for j in range(n_labels):
        label_vals = group_means[:, j]
        yes_mask = label_vals > 0.5
        no_mask = ~yes_mask
        yes_weight = float(np.sum(group_weights[yes_mask]))
        no_weight = float(np.sum(group_weights[no_mask]))
        smaller_side = min(yes_weight, no_weight)

        if smaller_side >= oscillation_fraction:
            # Neither side dominates — model is oscillating; suppress to midpoint
            pooled[j] = 0.5
        elif yes_weight >= no_weight:
            # "Yes" side dominates — use its weighted mean
            pooled[j] = float(np.sum(label_vals[yes_mask] * group_weights[yes_mask]) / yes_weight)
        else:
            # "No" side dominates — use its weighted mean
            pooled[j] = float(np.sum(label_vals[no_mask] * group_weights[no_mask]) / no_weight)

    return pooled
