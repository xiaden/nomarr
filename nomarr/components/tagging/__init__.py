"""
Tagging package.
"""

from .tagging_aggregation_comp import (
    LABEL_PAIRS,
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    get_prefix,
    load_calibrations,
    normalize_tag_label,
    simplify_label,
)
from .tagging_writer_comp import TagWriter

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
