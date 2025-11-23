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
from .writer import TagWriter

__all__ = [
    "TagWriter",
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "get_prefix",
    "load_calibrations",
    "normalize_tag_label",
    "simplify_label",
]
