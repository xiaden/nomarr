"""
Tagging package.
"""

from .tag_normalization_comp import (
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)
from .tagging_aggregation_comp import (
    LABEL_PAIRS,
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    get_prefix,
    load_calibrations,
    normalize_tag_label,
    simplify_label,
)
from .tagging_reader_comp import read_tags_from_file
from .tagging_remove_comp import remove_tags_from_file
from .tagging_writer_comp import TagWriter

__all__ = [
    "LABEL_PAIRS",
    "TagWriter",
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "get_prefix",
    "load_calibrations",
    "normalize_id3_tags",
    "normalize_mp4_tags",
    "normalize_tag_label",
    "normalize_vorbis_tags",
    "read_tags_from_file",
    "remove_tags_from_file",
    "simplify_label",
]
