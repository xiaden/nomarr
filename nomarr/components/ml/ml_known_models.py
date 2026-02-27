"""Known model defaults - label mappings for shipped ONNX head models.

Maps model stems (ONNX filenames without extension) to their output
label definitions.  Used by the model registration workflow to seed
``ml_model_outputs`` vertices with correct labels at startup.

When all outputs for a model have labels, the model is marked
``fully_configured=True`` and becomes eligible for inference.

Label strings come from ``mood_labels_comp.LABEL_PAIRS`` (columns 3-4)
and ``mood_labels_comp.MOOD_MAPPING`` - the human-readable names actually
written to tags, not raw sidecar class names.
"""

from __future__ import annotations

# Each entry: (output_index, label, is_positive, display_hint)
#
# - output_index: zero-based activation index in the ONNX output tensor
# - label: human-readable tag label written to the tag system
# - is_positive: True when higher activation = more of this quality
# - display_hint: UI grouping / category hint

KNOWN_MODELS: dict[str, list[tuple[int, str, bool, str]]] = {
    # -- effnet backbone ---------------------------------------------------
    "approachability_2c-discogs-effnet-1": [
        (0, "mainstream", True, "approachability"),
        (1, "fringe", True, "approachability"),
    ],
    "engagement_2c-discogs-effnet-1": [
        (0, "engaging", True, "engagement"),
        (1, "mellow", True, "engagement"),
    ],
    "timbre-discogs-effnet-1": [
        (0, "bright timbre", True, "timbre"),
        (1, "dark timbre", True, "timbre"),
    ],
    # -- musicnn backbone --------------------------------------------------
    "danceability-msd-musicnn-1": [
        (0, "easy dancing", True, "danceability"),
        (1, "hard dancing", True, "danceability"),
    ],
    "gender-msd-musicnn-1": [
        (0, "high-pitch vocal", True, "gender"),
        (1, "low-pitch vocal", True, "gender"),
    ],
    "mood_aggressive-msd-musicnn-1": [
        (0, "aggressive", True, "mood"),
        (1, "relaxed", True, "mood"),
    ],
    "mood_happy-msd-musicnn-1": [
        (0, "happy", True, "mood"),
        (1, "sad", True, "mood"),
    ],
    "mood_party-msd-musicnn-1": [
        (0, "not party-like", True, "mood"),
        (1, "party-like", True, "mood"),
    ],
    "mood_relaxed-msd-musicnn-1": [
        (0, "not relaxed", True, "mood"),
        (1, "relaxed", True, "mood"),
    ],
    "mood_sad-msd-musicnn-1": [
        (0, "not sad", True, "mood"),
        (1, "sad", True, "mood"),
    ],
    "tonal_atonal-msd-musicnn-1": [
        (0, "atonal", True, "tonality"),
        (1, "tonal", True, "tonality"),
    ],
    "voice_instrumental-msd-musicnn-1": [
        (0, "instrumental only", True, "voice-instrumental"),
        (1, "has vocals", True, "voice-instrumental"),
    ],
}
"""Mapping of shipped model stems to their output label definitions."""


def get_known_outputs(
    model_stem: str,
) -> list[tuple[int, str, bool, str]] | None:
    """Return known output defaults for a shipped model stem.

    Args:
        model_stem: ONNX filename stem
            (e.g. ``"mood_happy-msd-musicnn-1"``).

    Returns:
        List of ``(output_index, label, is_positive, display_hint)``
        tuples, or ``None`` if the stem is not a known model.

    """
    return KNOWN_MODELS.get(model_stem)
