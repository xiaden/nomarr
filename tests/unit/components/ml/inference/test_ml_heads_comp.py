"""Tests for ``nomarr.components.ml.inference.ml_heads_comp``."""

from __future__ import annotations

import pytest

from nomarr.components.ml.inference.ml_heads_comp import HeadDecision, HeadSpec
from nomarr.helpers.dto.ml_dto import HeadOutput
from nomarr.helpers.dto.ml_head_dto import HeadInfo


def _make_head_info(head_type: str = "sigmoid") -> HeadInfo:
    return HeadInfo(
        name="mood_happy",
        labels=["happy", "not_happy"],
        backbone="effnet",
        head_type=head_type,
        model_stem="mood_happy",
        model_path="/models/effnet/heads/sigmoid/mood_happy.onnx",
        embedding_graph="",
    )


def _make_multilabel_spec() -> HeadSpec:
    return HeadSpec(name="mood_happy", kind="sigmoid", labels=["happy", "not_happy"])


def _make_regression_spec() -> HeadSpec:
    return HeadSpec(
        name="approachability_regression",
        kind="regression",
        labels=["approachability"],
    )


@pytest.mark.unit
class TestHeadDecisionToHeadOutputs:
    """Tests for HeadDecision.to_head_outputs() accepting HeadInfo."""

    def test_accepts_head_info_and_produces_head_output_objects(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.9, "tier": "high"}}
        all_probs: dict[str, float] = {"not_happy": 0.1}
        decision = HeadDecision(spec, details, all_probs)
        hi = _make_head_info()

        outputs = decision.to_head_outputs(hi)

        assert len(outputs) > 0
        assert all(isinstance(o, HeadOutput) for o in outputs)

    def test_all_outputs_reference_the_given_head_info(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.9, "tier": "high"}}
        all_probs: dict[str, float] = {"not_happy": 0.1}
        decision = HeadDecision(spec, details, all_probs)
        hi = _make_head_info()

        outputs = decision.to_head_outputs(hi)

        assert all(o.head is hi for o in outputs)

    def test_regression_head_returns_empty_list(self) -> None:
        spec = _make_regression_spec()
        decision = HeadDecision(spec, {"approachability": 0.7}, {})
        hi = _make_head_info(head_type="regression")

        outputs = decision.to_head_outputs(hi)

        assert outputs == []

    def test_key_builder_produces_versioned_tag_key(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.9, "tier": "high"}}
        decision = HeadDecision(spec, details, {})
        hi = _make_head_info()

        def key_builder(label):
            return f"versioned_{label}"

        outputs = decision.to_head_outputs(hi, key_builder=key_builder)

        assert any(o.model_key == "versioned_happy" for o in outputs)

    def test_key_builder_sets_calibration_id_from_build_versioned_tag_key(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.9, "tier": "high"}}
        decision = HeadDecision(spec, details, {})
        hi = _make_head_info()

        outputs = decision.to_head_outputs(
            hi,
            key_builder=lambda label: f"versioned_{label}",
        )

        happy_out = next(o for o in outputs if o.label == "happy")
        assert happy_out.calibration_id == "none_0"

    def test_all_probs_key_builder_sets_calibration_id(self) -> None:
        spec = _make_multilabel_spec()
        details: dict[str, dict[str, float | str]] = {}
        all_probs: dict[str, float] = {"happy": 0.9}
        decision = HeadDecision(spec, details, all_probs)
        hi = _make_head_info()

        outputs = decision.to_head_outputs(
            hi,
            key_builder=lambda label: f"versioned_{label}",
        )

        happy_out = next(o for o in outputs if o.label == "happy")
        assert happy_out.calibration_id == "none_0"

    def test_outputs_include_both_details_and_all_probs(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.85, "tier": "medium"}}
        all_probs: dict[str, float] = {"not_happy": 0.15}
        decision = HeadDecision(spec, details, all_probs)
        hi = _make_head_info()

        outputs = decision.to_head_outputs(hi)

        labels = {o.label for o in outputs}
        assert "happy" in labels
        assert "not_happy" in labels

    def test_detail_label_has_tier(self) -> None:
        spec = _make_multilabel_spec()
        details = {"happy": {"p": 0.9, "tier": "high"}}
        decision = HeadDecision(spec, details, {})
        hi = _make_head_info()

        outputs = decision.to_head_outputs(hi)

        happy_out = next(o for o in outputs if o.label == "happy")
        assert happy_out.tier == "high"

    def test_all_probs_label_has_no_tier(self) -> None:
        spec = _make_multilabel_spec()
        details: dict = {}
        all_probs: dict[str, float] = {"not_happy": 0.15}
        decision = HeadDecision(spec, details, all_probs)
        hi = _make_head_info()

        outputs = decision.to_head_outputs(hi)

        not_happy_out = next(o for o in outputs if o.label == "not_happy")
        assert not_happy_out.tier is None

    def test_head_info_from_head_info_factory(self) -> None:
        """HeadSpec.from_head_info produces a spec that to_head_outputs accepts."""
        hi = _make_head_info()
        spec = HeadSpec.from_head_info(hi)
        details = {"happy": {"p": 0.9, "tier": "high"}}
        decision = HeadDecision(spec, details, {})

        outputs = decision.to_head_outputs(hi)

        assert all(o.head is hi for o in outputs)
