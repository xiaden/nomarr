"""Tag key mapping utilities for Navidrome integration.

Maps between model-tag storage keys and short display names (UX).

Model key pattern (from ml_head_dto.HeadInfo.build_versioned_tag_key):
    {label}_{backbone}_{model_stem}
    Example: happy_yamnet_mood_happy

Stored with nom: prefix:
    nom:happy_yamnet_mood_happy

Short name pattern:
    nom-{label} for string tags
    nom-{label}-raw for numeric tags (ML model outputs)

Examples:
    nom:happy_yamnet_mood_happy → nom-happy-raw
    nom:mood-strict → nom-mood-strict (already short, pass through)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Known backbone tokens used as field boundary markers in model keys.
# The key format is `{label}_{backbone}_{model_stem}`, where label and
# model_stem may contain underscores. We parse by locating backbone token.
_KNOWN_BACKBONES = ("effnet", "musicnn", "yamnet", "vggish")

# Tags that are already short (not versioned ML outputs)
_PASSTHROUGH_PREFIXES = (
    "mood-strict",
    "mood-regular",
    "mood-loose",
    "effnet_",
    "nom_version",
)


def is_versioned_ml_key(tag_name: str) -> bool:
    """Check if a tag name is a model-tag key.

    Args:
        tag_name: Full tag name (e.g., "nom:happy_yamnet_mood_happy")

    Returns:
        True if this is a model-tag key that needs short name mapping.

    """
    return _parse_model_key(tag_name) is not None


def extract_label_from_versioned_key(tag_name: str) -> str | None:
    """Extract the semantic label from a model-tag key.

    Args:
        tag_name: Full tag name (e.g., "nom:happy_yamnet_mood_happy")

    Returns:
        Label string (e.g., "happy") or None if not a model-tag key.

    """
    parsed = _parse_model_key(tag_name)
    if parsed is None:
        return None
    label, _, _ = parsed
    return label


def _parse_model_key(tag_name: str) -> tuple[str, str, str] | None:
    """Parse `{label}_{backbone}_{model_stem}` using known backbones as anchors."""
    key = tag_name.removeprefix("nom:")
    parts = key.split("_")
    if len(parts) < 3:
        return None

    for idx, part in enumerate(parts):
        if part.lower() not in _KNOWN_BACKBONES:
            continue
        if idx == 0:
            continue
        label = "_".join(parts[:idx])
        model_stem = "_".join(parts[idx + 1 :])
        if not model_stem:
            continue
        return (label, part, model_stem)
    return None


def make_short_tag_name(tag_name: str, is_numeric: bool = True) -> str:
    """Convert a tag name to a short display name for Navidrome.

    Args:
        tag_name: Full tag name (e.g., "nom:happy_yamnet_mood_happy")
        is_numeric: Whether the tag value is numeric (adds -raw suffix)

    Returns:
        Short name (e.g., "nom-happy-raw" or "nom-mood-strict")

    """
    # Strip nom: prefix
    key = tag_name.removeprefix("nom:")

    # Check if already short (passthrough)
    for prefix in _PASSTHROUGH_PREFIXES:
        if key.startswith(prefix):
            # Convert underscores to hyphens for consistency
            short = key.replace("_", "-")
            return f"nom-{short}"

    # Extract label from model key
    label = extract_label_from_versioned_key(tag_name)
    if label:
        # Versioned ML key → short name
        # Convert underscores to hyphens (not_happy → not-happy)
        short_label = label.replace("_", "-")
        if is_numeric:
            return f"nom-{short_label}-raw"
        return f"nom-{short_label}"

    # Fallback: just use the key with nom- prefix
    short = key.replace("_", "-")
    return f"nom-{short}"


def make_navidrome_field_name(short_name: str) -> str:
    """Convert short tag name to valid TOML field name.

    Navidrome TOML field names can't have hyphens, so we use underscores.

    Args:
        short_name: Short tag name (e.g., "nom-happy-raw")

    Returns:
        TOML field name (e.g., "nom_happy_raw")

    """
    return short_name.replace("-", "_")
