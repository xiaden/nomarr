"""Mood vocabulary — label constants and normalization.

Pure data + string utilities for mood-related label handling.
No aggregation logic, no ML imports, no IO.
"""

from __future__ import annotations


def normalize_tag_label(label: str) -> str:
    """Normalize model label for tag key consistency.

    Converts 'non_*' to 'not_*' for consistent naming.
    Example: 'non_happy' -> 'not_happy'

    Args:
        label: Raw label from model (e.g., 'happy', 'non_happy')

    Returns:
        Normalized label for use in tag keys

    """
    if label.startswith("non_"):
        return f"not_{label[4:]}"
    return label

MOOD_MAPPING: dict[str, tuple[str, str]] = {
    "approachability_regression": ("mainstream", "fringe"),
    "engagement_regression": ("engaging", "mellow"),
}
"""Regression head name → (high_term, low_term) for mood tier assignment."""
