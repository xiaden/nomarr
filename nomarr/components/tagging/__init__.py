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
from .tagging_writer_comp import TagWriterfrom nomarr.components.tagging.tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)


__all__ = [
    "LABEL_PAIRS",
    "TagWriter",
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "get_prefix",
    "load_calibrations",
    "normalize_tag_label",
    "simplify_label",
    "normalize_mp4_tags",
    "normalize_id3_tags",
    "normalize_vorbis_tags",
]
