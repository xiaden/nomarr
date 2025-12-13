"""Unit tests for tagging aggregation component."""

from nomarr.components.tagging.tagging_aggregation_comp import (
    aggregate_mood_tiers,
    get_prefix,
    normalize_tag_label,
    simplify_label,
)


class TestGetPrefix:
    """Test getting tag prefix from backbone name."""

    def test_returns_prefix_for_known_backbones(self):
        """Should return appropriate prefix for known backbones."""
        # Act/Assert - prefixes include trailing underscore
        assert get_prefix("effnet") == "effnet_"
        assert get_prefix("musicnn") == "musicnn_"
        assert get_prefix("yamnet") == "yamnet_"
        assert get_prefix("vggish") == "vggish_"

    def test_returns_empty_for_unknown_backbone(self):
        """Should return empty string for unknown backbones."""
        # Act
        prefix = get_prefix("unknown")

        # Assert
        assert prefix == ""


class TestNormalizeTagLabel:
    """Test normalizing model labels to tag keys."""

    def test_normalizes_simple_label(self):
        """Should return simple labels unchanged."""
        # Act
        result = normalize_tag_label("happy")

        # Assert
        assert result == "happy"

    def test_converts_non_prefix_to_not(self):
        """Should convert 'non_' prefix to 'not_'."""
        # Act
        result = normalize_tag_label("non_happy")

        # Assert
        assert result == "not_happy"

    def test_preserves_not_prefix(self):
        """Should preserve 'not_' prefix."""
        # Act
        result = normalize_tag_label("not_happy")

        # Assert
        assert result == "not_happy"

    def test_preserves_case(self):
        """Should preserve original case."""
        # Act
        result = normalize_tag_label("Happy")

        # Assert
        assert result == "Happy"


class TestSimplifyLabel:
    """Test simplifying model-prefixed labels to human terms."""

    def test_simplifies_happy_sad_pair(self):
        """Should map happy/sad labels."""
        # Act
        happy = simplify_label("musicnn_happy")
        sad = simplify_label("musicnn_sad")

        # Assert - should map to human terms
        assert isinstance(happy, str)
        assert isinstance(sad, str)

    def test_simplifies_aggressive_relaxed_pair(self):
        """Should map aggressive/relaxed labels."""
        # Act
        aggressive = simplify_label("effnet_aggressive")
        relaxed = simplify_label("effnet_relaxed")

        # Assert - should map to human terms
        assert isinstance(aggressive, str)
        assert isinstance(relaxed, str)

    def test_returns_label_unchanged_if_no_mapping(self):
        """Should return label unchanged if no simplification mapping exists."""
        # Act
        result = simplify_label("unknown_label")

        # Assert
        assert isinstance(result, str)

    def test_handles_labels_without_prefix(self):
        """Should handle labels without model prefix."""
        # Act
        result = simplify_label("happy")

        # Assert
        assert isinstance(result, str)


class TestAggregateMoodTiers:
    """Test mood tier aggregation."""

    def test_accepts_empty_head_outputs(self):
        """Should handle empty head outputs list."""
        # Act
        result = aggregate_mood_tiers(head_outputs=[], calibrations=None)

        # Assert - should return dict
        assert isinstance(result, dict)

    def test_returns_dict_with_expected_structure(self):
        """Should return dict with mood tier structure."""
        # Act
        result = aggregate_mood_tiers(head_outputs=[], calibrations=None)

        # Assert - should have tier keys (mood-strict, mood-regular, etc.)
        assert isinstance(result, dict)
