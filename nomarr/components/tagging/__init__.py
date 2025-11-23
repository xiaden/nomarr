"""
Tagging package.
"""

from .aggregation import (
    LABEL_PAIRS,
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    get_prefix,
    load_calibrations,
    normalize_tag_label,
    simplify_label,
)
from .writer import TagWriter

__all__ = [
    "LABEL_PAIRS",
    "TagWriter",
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "get_prefix",
    "load_calibrations",
    "normalize_tag_label",
    "simplify_label",
]
