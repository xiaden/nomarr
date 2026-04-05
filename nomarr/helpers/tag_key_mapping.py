"""Tag key mapping utilities for Navidrome integration.

Maps between versioned storage keys (reproducibility) and short display names (UX).

Versioned key pattern (from ml_discovery_comp.HeadInfo.build_versioned_tag_key):
    {label}_{framework}_{embedder}_{head}
    Example: happy_essentia21-beta6-dev_musicnn20200331_happy20220825

Stored with nom: prefix:
    nom:happy_essentia21-beta6-dev_musicnn20200331_happy20220825

Short name pattern:
    nom-{label} for string tags
    nom-{label}-raw for numeric tags (ML model outputs)

Examples:
    nom:happy_essentia21-beta6-dev_musicnn20200331_happy20220825 → nom-happy-raw
    nom:mood-strict → nom-mood-strict (already short, pass through)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Pattern for versioned ML model keys:
# {label}_essentia{version}_{backbone}{date}_{label}{date}
# The label appears twice: at start and in the head component
_VERSIONED_KEY_PATTERN = re.compile(
    r"^(?P<label>[a-z_]+)_essentia[\w.-]+_[a-z]+\d+_[a-z_]+\d+$",
    re.IGNORECASE,
)

# Tags that are already short (not versioned ML outputs)
_PASSTHROUGH_PREFIXES = (
    "mood-strict",
    "mood-regular",
    "mood-loose",
    "effnet_",
    "nom_version",
)


def is_versioned_ml_key(tag_rel: str) -> bool:
    """Check if a tag rel is a versioned ML model key.

    Args:
        tag_rel: Full tag rel (e.g., "nom:happy_essentia21-beta6-dev_...")

    Returns:
        True if this is a versioned ML key that needs short name mapping.

    """
    # Strip nom: prefix if present
    key = tag_rel.removeprefix("nom:")

    # Check if it matches the versioned pattern
    return _VERSIONED_KEY_PATTERN.match(key) is not None


def extract_label_from_versioned_key(tag_rel: str) -> str | None:
    """Extract the semantic label from a versioned ML tag key.

    Args:
        tag_rel: Full tag rel (e.g., "nom:happy_essentia21-beta6-dev_...")

    Returns:
        Label string (e.g., "happy") or None if not a versioned key.

    """
    # Strip nom: prefix if present
    key = tag_rel.removeprefix("nom:")

    match = _VERSIONED_KEY_PATTERN.match(key)
    if match:
        return match.group("label")
    return None


def make_short_tag_name(tag_rel: str, is_numeric: bool = True) -> str:
    """Convert a tag rel to a short display name for Navidrome.

    Args:
        tag_rel: Full tag rel (e.g., "nom:happy_essentia21-beta6-dev_...")
        is_numeric: Whether the tag value is numeric (adds -raw suffix)

    Returns:
        Short name (e.g., "nom-happy-raw" or "nom-mood-strict")

    """
    # Strip nom: prefix
    key = tag_rel.removeprefix("nom:")

    # Check if already short (passthrough)
    for prefix in _PASSTHROUGH_PREFIXES:
        if key.startswith(prefix):
            # Convert underscores to hyphens for consistency
            short = key.replace("_", "-")
            return f"nom-{short}"

    # Extract label from versioned key
    label = extract_label_from_versioned_key(tag_rel)
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
