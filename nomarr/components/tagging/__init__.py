"""Tagging package."""

from .mood_labels_comp import normalize_tag_label
from .tag_normalization_comp import (
    CANONICAL_TAGS,
    MP4_FREEFORM_BLOCKLIST,
    normalize_id3_tags,
    normalize_mp4_tags,
    normalize_vorbis_tags,
)
from .tagging_aggregation_comp import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
)
from .tagging_reader_comp import read_tags_from_file
from .tagging_remove_comp import remove_tags_from_file
from .tagging_writer_comp import TagWriter

__all__ = [
    "CANONICAL_TAGS",
    "MP4_FREEFORM_BLOCKLIST",
    "TagWriter",
    "add_regression_mood_tiers",
    "aggregate_mood_tiers",
    "normalize_id3_tags",
    "normalize_mp4_tags",
    "normalize_tag_label",
    "normalize_vorbis_tags",
    "read_tags_from_file",
    "remove_tags_from_file",
]
