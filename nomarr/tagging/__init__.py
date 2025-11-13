"""
Tagging package.
"""

from .aggregation import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    get_prefix,
    load_calibrations,
    normalize_tag_label,
    simplify_label,
)

__all__ = [
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "get_prefix",
    "load_calibrations",
    "normalize_tag_label",
    "simplify_label",
]
