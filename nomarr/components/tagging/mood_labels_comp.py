"""Mood vocabulary — label constants, normalization, and simplification.

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


def simplify_label(base_key: str) -> str:
    """Map model-prefixed labels to human terms: 'yamnet_non_happy' -> 'not happy', 'effnet_bright' -> 'bright'."""
    label_stripped = base_key.lower()
    for pref in ("yamnet_", "vggish_", "effnet_", "musicnn_"):
        if label_stripped.startswith(pref):
            label_stripped = label_stripped[len(pref) :]
            break
    if label_stripped.startswith("non_"):
        core = label_stripped[4:]
        return f"not {core.replace('_', ' ')}"
    if label_stripped.startswith("not_"):
        core = label_stripped[4:]
        return f"not {core.replace('_', ' ')}"
    return label_stripped.replace("_", " ")


LABEL_PAIRS: list[tuple[str, str, str, str]] = [
    ("happy", "sad", "peppy", "sombre"),
    ("aggressive", "relaxed", "aggressive", "relaxed"),
    ("electronic", "acoustic", "synth-like", "acoustic-like"),
    ("party", "not_party", "party-like", "not party-like"),
    ("danceable", "not_danceable", "easy to dance to", "hard to dance to"),
    ("bright", "dark", "bright timbre", "dark timbre"),
    ("male", "female", "low-pitch vocal", "high-pitch vocal"),
    ("tonal", "atonal", "tonal", "atonal"),
    ("instrumental", "voice", "instrumental only", "has vocals"),
]
"""Opposing mood pairs: (pos_pat, neg_pat, pos_human_label, neg_human_label).

Used by aggregation to suppress conflicting tiers and to build
human-readable label maps.
"""

MOOD_MAPPING: dict[str, tuple[str, str]] = {
    "approachability_regression": ("mainstream", "fringe"),
    "engagement_regression": ("engaging", "mellow"),
}
"""Regression head name → (high_term, low_term) for mood tier assignment."""
