"""Known model defaults - label mappings for shipped ONNX head models.

Maps model stems (ONNX filenames without extension) to their output
label definitions.  Used by the model registration workflow to seed
``ml_model_outputs`` vertices with correct labels at startup.

When all outputs for a model have labels, the model is marked
``fully_configured=True`` and becomes eligible for inference.

Label strings are authoritative human-readable display terms, written
directly to the tag system at inference time.

Output indices match the class ordering declared in the upstream MTG Essentia
model metadata.  For example ``voice_instrumental`` → index 0 is
"instrumental only" (instrumental), index 1 is "has vocals" (voice).
See ``docs/upstream/modelsinfo.md`` for the authoritative class lists.

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
# Output order matches the upstream MTG Essentia model training.
# See the module docstring and docs/upstream/modelsinfo.md for details.

KNOWN_MODELS: dict[str, list[tuple[int, str]]] = {
    # -- effnet backbone ---------------------------------------------------
    "approachability_2c-discogs-effnet-1": [
        (0, "Mainstream"),
        (1, "Fringe"),
    ],
    "engagement_2c-discogs-effnet-1": [
        (0, "Atmospheric"),
        (1, "Captivating"),
    ],
    "timbre-discogs-effnet-1": [
        (0, "Bright timbre"),
        (1, "Dark timbre"),
    ],
    # -- musicnn backbone --------------------------------------------------
    "danceability-msd-musicnn-1": [
        (0, "Easy dancing"),
        (1, "Hard dancing"),
    ],
    "gender-msd-musicnn-1": [
        (0, "High-pitch vocal"),
        (1, "Low-pitch vocal"),
    ],
    "mood_aggressive-msd-musicnn-1": [
        (0, "Aggressive"),
        (1, "Relaxed"),
    ],
    "mood_happy-msd-musicnn-1": [
        (0, "Happy"),
        (1, "Not happy"),
    ],
    "mood_party-msd-musicnn-1": [
        (0, "Party-like"),
        (1, "Not party-like"),
    ],
    "mood_relaxed-msd-musicnn-1": [
        (0, "Relaxed"),
        (1, "Not relaxed"),
    ],
    "mood_sad-msd-musicnn-1": [
        (0, "Sad"),
        (1, "Not sad"),
    ],
    "tonal_atonal-msd-musicnn-1": [
        (0, "Atonal"),
        (1, "Tonal"),
    ],
    "voice_instrumental-msd-musicnn-1": [
        (0, "Instrumental only"),
        (1, "Has vocals"),
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
