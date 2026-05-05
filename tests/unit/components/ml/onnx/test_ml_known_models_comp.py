"""Tests for ``nomarr.components.ml.onnx.ml_known_models_comp``.

Verifies that the label index ordering in KNOWN_MODELS matches the upstream
MTG Essentia model metadata (see ``docs/upstream/modelsinfo.md``).  These tests
guard against accidental re-reversal of the class orderings.
"""

from __future__ import annotations

import pytest

from nomarr.components.ml.onnx.ml_known_models_comp import (
    KNOWN_MODELS,
    OPPONENT_MAP,
    build_opponent_map,
    get_known_outputs,
)


@pytest.mark.unit
class TestKnownModelsLabelOrdering:
    """Guard tests for class-index ordering in KNOWN_MODELS.

    Each test pins the label at index 0 for a specific model stem to prevent
    silent re-reversal of the bug fixed in this PR.  The authoritative class
    lists come from ``docs/upstream/modelsinfo.md``.
    """

    def _label_at(self, stem: str, index: int) -> str:
        outputs = KNOWN_MODELS[stem]
        label = next((label for idx, label in outputs if idx == index), None)
        assert label is not None, f"No output at index {index} for model '{stem}'"
        return label

    # -- voice/instrumental (upstream: "instrumental, voice") ----------------

    def test_voice_instrumental_index0_is_instrumental(self) -> None:
        """Index 0 of voice_instrumental is the *instrumental* class."""
        assert self._label_at("voice_instrumental-msd-musicnn-1", 0) == "instrumental only"

    def test_voice_instrumental_index1_is_voice(self) -> None:
        """Index 1 of voice_instrumental is the *voice* (has vocals) class."""
        assert self._label_at("voice_instrumental-msd-musicnn-1", 1) == "has vocals"

    # -- tonal/atonal (upstream: "atonal, tonal") ----------------------------

    def test_tonal_atonal_index0_is_atonal(self) -> None:
        """Index 0 of tonal_atonal is the *atonal* class."""
        assert self._label_at("tonal_atonal-msd-musicnn-1", 0) == "atonal"

    def test_tonal_atonal_index1_is_tonal(self) -> None:
        """Index 1 of tonal_atonal is the *tonal* class."""
        assert self._label_at("tonal_atonal-msd-musicnn-1", 1) == "tonal"

    # -- engagement (upstream model: idx0=low-engagement/mellow, idx1=engaging)

    def test_engagement_2c_index0_is_mellow(self) -> None:
        """Index 0 of engagement_2c is the *low-engagement* (mellow) class."""
        assert self._label_at("engagement_2c-discogs-effnet-1", 0) == "mellow"

    def test_engagement_2c_index1_is_engaging(self) -> None:
        """Index 1 of engagement_2c is the *high-engagement* (engaging) class."""
        assert self._label_at("engagement_2c-discogs-effnet-1", 1) == "engaging"

    # -- mood models (upstream: "positive, non_positive") --------------------

    def test_mood_happy_index0_is_happy(self) -> None:
        assert self._label_at("mood_happy-msd-musicnn-1", 0) == "happy"

    def test_mood_aggressive_index0_is_aggressive(self) -> None:
        assert self._label_at("mood_aggressive-msd-musicnn-1", 0) == "aggressive"

    def test_mood_party_index0_is_party_like(self) -> None:
        assert self._label_at("mood_party-msd-musicnn-1", 0) == "party-like"

    def test_mood_relaxed_index0_is_relaxed(self) -> None:
        assert self._label_at("mood_relaxed-msd-musicnn-1", 0) == "relaxed"

    def test_mood_sad_index0_is_sad(self) -> None:
        assert self._label_at("mood_sad-msd-musicnn-1", 0) == "sad"

    # -- other models --------------------------------------------------------

    def test_danceability_index0_is_easy_dancing(self) -> None:
        """Index 0 is the *danceable* class (upstream: "danceable, not_danceable")."""
        assert self._label_at("danceability-msd-musicnn-1", 0) == "easy dancing"

    def test_gender_index0_is_high_pitch(self) -> None:
        """Index 0 is the *female/high-pitch* class (upstream: "female, male")."""
        assert self._label_at("gender-msd-musicnn-1", 0) == "high-pitch vocal"

    def test_timbre_index0_is_bright(self) -> None:
        """Index 0 is the *bright* class (upstream: "bright, dark")."""
        assert self._label_at("timbre-discogs-effnet-1", 0) == "bright timbre"


@pytest.mark.unit
class TestGetKnownOutputs:
    """Tests for ``get_known_outputs``."""

    def test_returns_none_for_unknown_stem(self) -> None:
        assert get_known_outputs("unknown-model-1") is None

    def test_returns_label_list_for_known_stem(self) -> None:
        result = get_known_outputs("voice_instrumental-msd-musicnn-1")
        assert result is not None
        assert len(result) == 2

    def test_returned_list_contains_index_label_tuples(self) -> None:
        result = get_known_outputs("mood_happy-msd-musicnn-1")
        assert result is not None
        for item in result:
            assert len(item) == 2
            idx, label = item
            assert isinstance(idx, int)
            assert isinstance(label, str)


@pytest.mark.unit
class TestBuildOpponentMap:
    """Tests for ``build_opponent_map``."""

    def test_empty_input_returns_empty_map(self) -> None:
        assert build_opponent_map({}) == {}

    def test_single_model_with_two_labels_creates_mutual_opponents(self) -> None:
        result = build_opponent_map({"m": [(0, "a"), (1, "b")]})
        assert "a" in result and "b" in result["a"]
        assert "b" in result and "a" in result["b"]

    def test_single_label_model_creates_no_opponents(self) -> None:
        result = build_opponent_map({"m": [(0, "a")]})
        assert result.get("a", set()) == set()

    def test_labels_shared_across_stems_accumulate_opponents(self) -> None:
        models = {
            "m1": [(0, "aggressive"), (1, "relaxed")],
            "m2": [(0, "relaxed"), (1, "not relaxed")],
        }
        result = build_opponent_map(models)
        assert "not relaxed" in result.get("relaxed", set())
        assert "aggressive" in result.get("relaxed", set())

    def test_opponent_map_module_constant_reflects_known_models(self) -> None:
        """The module-level OPPONENT_MAP should equal the result of build_opponent_map(KNOWN_MODELS)."""
        expected = build_opponent_map(KNOWN_MODELS)
        assert OPPONENT_MAP == expected

    def test_has_vocals_and_instrumental_only_are_opponents(self) -> None:
        assert "instrumental only" in OPPONENT_MAP.get("has vocals", set())
        assert "has vocals" in OPPONENT_MAP.get("instrumental only", set())

    def test_tonal_and_atonal_are_opponents(self) -> None:
        assert "atonal" in OPPONENT_MAP.get("tonal", set())
        assert "tonal" in OPPONENT_MAP.get("atonal", set())

    def test_engaging_and_mellow_are_opponents(self) -> None:
        assert "mellow" in OPPONENT_MAP.get("engaging", set())
        assert "engaging" in OPPONENT_MAP.get("mellow", set())
