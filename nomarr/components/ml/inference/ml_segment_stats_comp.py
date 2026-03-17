"""Segment-level statistics computation for ML head predictions.

Stateless, pure component: takes numpy arrays and labels, returns aggregated
statistics dicts. No DB or config dependencies.
"""

from typing import Any

import numpy as np


def compute_segment_stats(
    segment_scores: np.ndarray,
    labels: list[str],
) -> list[dict[str, Any]]:
    """Compute per-label statistics from segment-level predictions.

    Given a matrix of shape [num_segments, num_classes] and a label list,
    returns one dict per label with mean, std, min, and max across segments.

    Args:
        segment_scores: Array of shape [num_segments, num_classes]
        labels: Label names, length must equal num_classes

    Returns:
        List of {"label": str, "mean": float, "std": float, "min": float, "max": float}
        dicts, one per label/class.

    Raises:
        ValueError: If segment_scores.shape[1] != len(labels)

    """
    if not labels:
        return []

    if segment_scores.ndim != 2:
        msg = f"segment_scores must be 2D [num_segments, num_classes], got shape {segment_scores.shape}"
        raise ValueError(msg)

    num_classes = segment_scores.shape[1]
    if num_classes != len(labels):
        msg = (
            f"Shape mismatch: segment_scores has {num_classes} classes "
            f"but {len(labels)} labels provided"
        )
        raise ValueError(msg)

    stats: list[dict[str, Any]] = []
    for i, label in enumerate(labels):
        col = segment_scores[:, i]
        stats.append({
            "label": label,
            "mean": float(np.mean(col)),
            "std": float(np.std(col)),
            "min": float(np.min(col)),
            "max": float(np.max(col)),
        })

    return stats
