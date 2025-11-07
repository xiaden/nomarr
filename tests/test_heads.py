"""
Unit tests for nomarr/models/heads.py
"""

import numpy as np
import pytest

from nomarr.ml.models.discovery import Sidecar
from nomarr.ml.models.heads import (
    HeadDecision,
    HeadSpec,
    decide_multiclass_adaptive,
    decide_multilabel,
    decide_regression,
    head_is_multiclass,
    head_is_multilabel,
    head_is_regression,
)


@pytest.mark.unit
class TestHeadTypeDetection:
    """Test head type detection functions."""

    def test_head_is_multilabel(self, mock_multilabel_sidecar):
        """Test multilabel detection."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        assert head_is_multilabel(spec) is True

    def test_head_is_multiclass(self, mock_sidecar):
        """Test multiclass detection."""
        sidecar = Sidecar(path="test.json", data=mock_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        assert head_is_multiclass(spec) is True

    def test_head_is_regression(self, mock_regression_sidecar):
        """Test regression detection."""
        sidecar = Sidecar(path="test.json", data=mock_regression_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        assert head_is_regression(spec) is True

    def test_multilabel_not_multiclass(self, mock_multilabel_sidecar):
        """Test that multilabel is not detected as multiclass."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        assert head_is_multiclass(spec) is False

    def test_regression_not_multilabel(self, mock_regression_sidecar):
        """Test that regression is not detected as multilabel."""
        sidecar = Sidecar(path="test.json", data=mock_regression_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        assert head_is_multilabel(spec) is False


@pytest.mark.unit
class TestDecideMultilabel:
    """Test multilabel decision logic."""

    def test_decide_multilabel_above_threshold(self, mock_multilabel_sidecar):
        """Test that labels above threshold are selected."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        # Override cascade to set specific thresholds
        spec.cascade.low = 0.5
        spec.label_thresholds = {"tag1": 0.5, "tag2": 0.5, "tag3": 0.5}

        pooled = np.array([0.8, 0.3, 0.6], dtype=np.float32)
        result = decide_multilabel(pooled, spec)

        assert isinstance(result, dict)
        # Result now has "selected" and "all_probs" keys
        assert "selected" in result
        assert "all_probs" in result
        selected = result["selected"]
        all_probs = result["all_probs"]

        # Check selected tags (with tiers)
        assert "tag1" in selected
        assert "tag3" in selected
        assert "tag2" not in selected
        assert selected["tag1"]["p"] == pytest.approx(0.8, rel=1e-5)
        assert selected["tag3"]["p"] == pytest.approx(0.6, rel=1e-5)

        # Check all probabilities are present
        assert "tag1" in all_probs
        assert "tag2" in all_probs
        assert "tag3" in all_probs
        assert all_probs["tag1"] == pytest.approx(0.8, rel=1e-5)
        assert all_probs["tag2"] == pytest.approx(0.3, rel=1e-5)
        assert all_probs["tag3"] == pytest.approx(0.6, rel=1e-5)

    def test_decide_multilabel_custom_threshold(self, mock_multilabel_sidecar):
        """Test multilabel with custom threshold."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        spec.cascade.low = 0.6
        spec.label_thresholds = {"tag1": 0.6, "tag2": 0.6, "tag3": 0.6}

        pooled = np.array([0.7, 0.5, 0.3], dtype=np.float32)
        result = decide_multilabel(pooled, spec)

        selected = result["selected"]
        all_probs = result["all_probs"]

        # Check selected tags
        assert "tag1" in selected
        assert "tag2" not in selected
        assert "tag3" not in selected

        # Check all probabilities are present
        assert "tag1" in all_probs
        assert "tag2" in all_probs
        assert "tag3" in all_probs

    def test_decide_multilabel_no_tags(self, mock_multilabel_sidecar):
        """Test multilabel when no tags exceed threshold."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        spec.cascade.low = 0.5
        spec.label_thresholds = {"tag1": 0.5, "tag2": 0.5, "tag3": 0.5}

        pooled = np.array([0.2, 0.3, 0.1], dtype=np.float32)
        result = decide_multilabel(pooled, spec)

        selected = result["selected"]
        all_probs = result["all_probs"]

        # Selected should be empty when no tags meet threshold
        assert len(selected) == 0

        # But all probabilities should still be present
        assert len(all_probs) == 3
        assert "tag1" in all_probs
        assert "tag2" in all_probs
        assert "tag3" in all_probs

    def test_decide_multilabel_all_tags(self, mock_multilabel_sidecar):
        """Test multilabel when all tags exceed threshold."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)
        spec.cascade.low = 0.5
        spec.label_thresholds = {"tag1": 0.5, "tag2": 0.5, "tag3": 0.5}

        pooled = np.array([0.9, 0.8, 0.7], dtype=np.float32)
        result = decide_multilabel(pooled, spec)

        selected = result["selected"]
        all_probs = result["all_probs"]

        # All tags should be selected
        assert len(selected) == 3
        assert all(label in selected for label in ["tag1", "tag2", "tag3"])

        # All probabilities should be present
        assert len(all_probs) == 3
        assert all(label in all_probs for label in ["tag1", "tag2", "tag3"])


@pytest.mark.unit
class TestDecideRegression:
    """Test regression decision logic."""

    def test_decide_regression_single_value(self):
        """Test regression with single output value."""
        labels = ["energy"]
        pooled = np.array([0.75], dtype=np.float32)

        result = decide_regression(pooled, labels)

        assert isinstance(result, dict)
        assert "energy" in result
        assert result["energy"] == pytest.approx(0.75, rel=1e-5)

    def test_decide_regression_multiple_values(self):
        """Test regression with multiple output values."""
        labels = ["valence", "arousal", "dominance"]
        pooled = np.array([0.3, 0.8, 0.5], dtype=np.float32)

        result = decide_regression(pooled, labels)

        assert len(result) == 3
        assert result["valence"] == pytest.approx(0.3, rel=1e-5)
        assert result["arousal"] == pytest.approx(0.8, rel=1e-5)
        assert result["dominance"] == pytest.approx(0.5, rel=1e-5)


@pytest.mark.unit
class TestDecideMulticlassAdaptive:
    """Test adaptive multiclass decision logic."""

    def test_decide_multiclass_single_winner(self, mock_sidecar):
        """Test multiclass with clear winner."""
        sidecar = Sidecar(path="test.json", data=mock_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)

        pooled = np.array([0.8, 0.1, 0.05, 0.03, 0.02], dtype=np.float32)
        result = decide_multiclass_adaptive(pooled, spec)

        assert isinstance(result, dict)
        assert "class_a" in result
        # Top label should be present

    def test_decide_multiclass_close_race(self, mock_sidecar):
        """Test multiclass with close competition."""
        sidecar = Sidecar(path="test.json", data=mock_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)

        # First two classes have close scores
        pooled = np.array([0.4, 0.35, 0.15, 0.06, 0.04], dtype=np.float32)
        result = decide_multiclass_adaptive(pooled, spec)

        # With close competition, top candidates should be included
        assert isinstance(result, dict)
        assert len(result) >= 1  # At least top class

    def test_decide_multiclass_uniform_distribution(self, mock_sidecar):
        """Test multiclass with uniform distribution."""
        sidecar = Sidecar(path="test.json", data=mock_sidecar)
        spec = HeadSpec.from_sidecar(sidecar)

        pooled = np.array([0.2, 0.2, 0.2, 0.2, 0.2], dtype=np.float32)
        result = decide_multiclass_adaptive(pooled, spec)

        # With uniform distribution, should handle gracefully
        assert isinstance(result, dict)
        assert len(result) > 0


@pytest.mark.unit
class TestHeadDecision:
    """Test HeadDecision dataclass."""

    def test_head_decision_creation(self, mock_multilabel_sidecar):
        """Test creating a HeadDecision via run_head_decision."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)

        decision = HeadDecision(
            head=HeadSpec.from_sidecar(sidecar),
            details={"tag1": {"p": 0.8, "tier": "high"}, "tag3": {"p": 0.6, "tier": "medium"}},
        )

        assert hasattr(decision, "head")
        assert hasattr(decision, "details")
        assert decision.details["tag1"]["p"] == 0.8

    def test_head_decision_as_tags(self, mock_multilabel_sidecar):
        """Test converting HeadDecision to tags."""
        sidecar = Sidecar(path="test.json", data=mock_multilabel_sidecar)
        # Details should match decide_multilabel format: {"tag": {"p": float, "tier": str}}
        decision = HeadDecision(
            head=HeadSpec.from_sidecar(sidecar),
            details={"tag1": {"p": 0.8, "tier": "high"}, "tag3": {"p": 0.6, "tier": "medium"}},
        )

        tags = decision.as_tags(prefix="test_")
        assert isinstance(tags, dict)
        # as_tags() extracts the "p" values and adds prefix
        assert "test_tag1" in tags or "tag1" in tags  # Depending on implementation
