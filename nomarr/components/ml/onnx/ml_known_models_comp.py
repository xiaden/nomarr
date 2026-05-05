"""Known model defaults - label mappings for shipped ONNX head models.

Maps model stems (ONNX filenames without extension) to their output
label definitions.  Used by the model registration workflow to seed
``ml_model_outputs`` vertices with correct labels at startup.

When all outputs for a model have labels, the model is marked
``fully_configured=True`` and becomes eligible for inference.

Label strings are authoritative human-readable display terms, written
directly to the tag system at inference time.

Output indices follow the MTG Essentia model metadata
(``docs/upstream/modelsinfo.md``), **not** the filename stem word order.
Always verify against the upstream class list for each model:

- ``voice_instrumental``: idx 0 = "instrumental only", idx 1 = "has vocals"
- ``tonal_atonal``:       idx 0 = "atonal",            idx 1 = "tonal"
- ``engagement_2c``:     idx 0 = "mellow",             idx 1 = "engaging"

``OPPONENT_MAP`` is derived at module load from ``KNOWN_MODELS``: for each
model stem, all co-defined output labels are declared mutual opponents.  Any
two labels that co-occur within the same stem are therefore treated as
semantically contradictory, enabling cross-head conflict suppression without
a manually maintained pair table.
"""

from __future__ import annotations

# Each entry: (output_index, label)
#
# - output_index: zero-based activation index in the ONNX output tensor
# - label: human-readable tag label written to the tag system
#
# Output order follows the upstream Essentia model metadata (see docstring
# above).  Do NOT infer ordering from the model stem word order — several
# models have stems whose first word does not match the idx-0 class.

KNOWN_MODELS: dict[str, list[tuple[int, str]]] = {
    # -- effnet backbone ---------------------------------------------------
    "approachability_2c-discogs-effnet-1": [
        (0, "mainstream"),
        (1, "fringe"),
    ],
    "engagement_2c-discogs-effnet-1": [
        (0, "mellow"),
        (1, "engaging"),
    ],
    "timbre-discogs-effnet-1": [
        (0, "bright timbre"),
        (1, "dark timbre"),
    ],
    # -- musicnn backbone --------------------------------------------------
    "danceability-msd-musicnn-1": [
        (0, "easy dancing"),
        (1, "hard dancing"),
    ],
    "gender-msd-musicnn-1": [
        (0, "high-pitch vocal"),
        (1, "low-pitch vocal"),
    ],
    "mood_aggressive-msd-musicnn-1": [
        (0, "aggressive"),
        (1, "relaxed"),
    ],
    "mood_happy-msd-musicnn-1": [
        (0, "happy"),
        (1, "not happy"),
    ],
    "mood_party-msd-musicnn-1": [
        (0, "party-like"),
        (1, "not party-like"),
    ],
    "mood_relaxed-msd-musicnn-1": [
        (0, "relaxed"),
        (1, "not relaxed"),
    ],
    "mood_sad-msd-musicnn-1": [
        (0, "sad"),
        (1, "not sad"),
    ],
    "tonal_atonal-msd-musicnn-1": [
        (0, "atonal"),
        (1, "tonal"),
    ],
    "voice_instrumental-msd-musicnn-1": [
        (0, "instrumental only"),
        (1, "has vocals"),
    ],
}
"""Mapping of shipped model stems to their output label definitions."""


def get_known_outputs(
    model_stem: str,
) -> list[tuple[int, str]] | None:
    """Return known output defaults for a shipped model stem.

    Args:
        model_stem: ONNX filename stem
            (e.g. ``"mood_happy-msd-musicnn-1"``).

    Returns:
        List of ``(output_index, label)`` tuples, or ``None`` if the stem
        is not a known model.

    """
    return KNOWN_MODELS.get(model_stem)


def build_opponent_map(
    known_models: dict[str, list[tuple[int, str]]],
) -> dict[str, set[str]]:
    """Derive a semantic opponent map from KNOWN_MODELS.

    For each model stem, every pair of co-defined output labels is treated as
    mutually opposing.  The resulting map is flat: ``label -> set of opponent
    labels``.

    This enables conflict suppression without a hand-maintained pair table.
    Cross-head conflicts are covered because labels that appear in multiple
    stems (e.g. ``"relaxed"`` in both ``mood_aggressive`` and
    ``mood_relaxed``) carry opponent relationships from all their source stems.

    Args:
        known_models: The ``KNOWN_MODELS`` dict.

    Returns:
        Mapping of each label to the set of labels it opposes.

    """
    opponent_map: dict[str, set[str]] = {}
    for outputs in known_models.values():
        labels = [label for _, label in outputs]
        for label_a in labels:
            for label_b in labels:
                if label_a != label_b:
                    opponent_map.setdefault(label_a, set()).add(label_b)
    return opponent_map


OPPONENT_MAP: dict[str, set[str]] = build_opponent_map(KNOWN_MODELS)
"""Derived semantic opponent map — see :func:`build_opponent_map`."""
