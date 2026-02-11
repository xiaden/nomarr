"""Unit tests for parse_smart_playlist_query_wf module.

Tests parser edge cases for nested rule groups:
- Empty groups rejection
- Unmatched parentheses rejection
- Max depth enforcement
- Valid nested expression parsing
- Backward compatibility with flat queries
"""

import pytest

from nomarr.helpers.dto.navidrome_dto import MAX_RULE_GROUP_DEPTH, RuleGroup
from nomarr.helpers.exceptions import PlaylistQueryError
from nomarr.workflows.navidrome.parse_smart_playlist_query_wf import (
    _tokenize_parentheses,
    parse_smart_playlist_query,
)


class TestEmptyGroupRejection:
    """P1-S1: Parser should reject empty groups with clear error."""

    @pytest.mark.unit
    def test_empty_query_raises_error(self) -> None:
        """Empty query string should raise PlaylistQueryError."""
        with pytest.raises(PlaylistQueryError, match="Query cannot be empty"):
            parse_smart_playlist_query("")

    @pytest.mark.unit
    def test_whitespace_only_raises_error(self) -> None:
        """Whitespace-only query should raise PlaylistQueryError."""
        with pytest.raises(PlaylistQueryError, match="Query cannot be empty"):
            parse_smart_playlist_query("   ")

    @pytest.mark.unit
    def test_empty_parentheses_raises_error(self) -> None:
        """Empty parentheses () should raise PlaylistQueryError."""
        with pytest.raises(PlaylistQueryError, match="Empty query segment"):
            parse_smart_playlist_query("()")

    @pytest.mark.unit
    def test_nested_empty_parentheses_raises_error(self) -> None:
        """Nested empty parentheses (()) should raise PlaylistQueryError."""
        with pytest.raises(PlaylistQueryError, match="Empty query segment"):
            parse_smart_playlist_query("(())")

    @pytest.mark.unit
    def test_empty_group_in_or_expression(self) -> None:
        """Empty group in OR expression should raise PlaylistQueryError."""
        with pytest.raises(PlaylistQueryError, match="Empty query segment"):
            parse_smart_playlist_query("tag:mood > 0.5 OR ()")


class TestUnmatchedParentheses:
    """P1-S2: Parser should reject unmatched parentheses."""

    @pytest.mark.unit
    def test_unclosed_opening_paren(self) -> None:
        """Unclosed opening parenthesis should raise error."""
        with pytest.raises(PlaylistQueryError, match="unclosed"):
            parse_smart_playlist_query("(tag:mood > 0.5 AND tag:energy > 0.7")

    @pytest.mark.unit
    def test_extra_closing_paren(self) -> None:
        """Extra closing parenthesis should raise error."""
        with pytest.raises(PlaylistQueryError, match="closing"):
            parse_smart_playlist_query("tag:mood > 0.5) AND tag:energy > 0.7")

    @pytest.mark.unit
    def test_closing_before_opening(self) -> None:
        """Closing paren before opening should raise error."""
        with pytest.raises(PlaylistQueryError, match="closing"):
            parse_smart_playlist_query(")tag:mood > 0.5(")

    @pytest.mark.unit
    def test_multiple_unclosed_parens(self) -> None:
        """Multiple unclosed parentheses should raise error."""
        with pytest.raises(PlaylistQueryError, match="unclosed"):
            parse_smart_playlist_query("((tag:mood > 0.5")

    @pytest.mark.unit
    def test_mismatched_in_complex_expression(self) -> None:
        """Mismatched parens in complex expression should raise error."""
        with pytest.raises(PlaylistQueryError, match=r"unclosed|closing"):
            parse_smart_playlist_query("(tag:a > 0.5 AND (tag:b > 0.6) OR tag:c > 0.7")


class TestMaxDepthEnforcement:
    """P1-S3: Parser should reject queries exceeding max depth."""

    @pytest.mark.unit
    def test_exceeds_max_depth_in_tokenizer(self) -> None:
        """Queries exceeding max depth should raise error in tokenizer."""
        # Build query with nesting depth = MAX_RULE_GROUP_DEPTH + 1
        inner = "tag:test > 0.5"
        for _ in range(MAX_RULE_GROUP_DEPTH + 1):
            inner = f"({inner})"

        with pytest.raises(PlaylistQueryError, match=r"exceeds maximum|exceeded"):
            _tokenize_parentheses(inner)

    @pytest.mark.unit
    def test_max_depth_enforced_in_parse_group(self) -> None:
        """Recursive parsing should enforce max depth."""
        # Build deeply nested query
        inner = "tag:test > 0.5"
        for _ in range(MAX_RULE_GROUP_DEPTH + 1):
            inner = f"({inner})"

        with pytest.raises(PlaylistQueryError, match=r"exceeded|exceeds maximum"):
            parse_smart_playlist_query(inner)

    @pytest.mark.unit
    def test_at_max_depth_succeeds(self) -> None:
        """Query at exactly max depth should succeed."""
        # Build query with nesting depth = MAX_RULE_GROUP_DEPTH - 1
        # (outer parse_group starts at depth=0, each paren layer adds 1)
        inner = "tag:test > 0.5"
        for _ in range(MAX_RULE_GROUP_DEPTH - 1):
            inner = f"({inner})"

        # Should not raise
        result = parse_smart_playlist_query(inner)
        assert result.root is not None


class TestDeeplyNestedValidExpressions:
    """P1-S4: Valid deeply nested expressions should parse correctly."""

    @pytest.mark.unit
    def test_simple_nested_and_or(self) -> None:
        """(A AND B) OR C should parse correctly."""
        query = "(tag:mood > 0.5 AND tag:energy > 0.6) OR tag:calm > 0.7"
        result = parse_smart_playlist_query(query)

        # Root should be OR
        assert result.root.logic == "OR"
        # Should have one nested group and one condition
        assert len(result.root.groups) == 1
        assert len(result.root.conditions) == 1
        # Nested group should be AND
        assert result.root.groups[0].logic == "AND"
        assert len(result.root.groups[0].conditions) == 2

    @pytest.mark.unit
    def test_nested_with_both_operators(self) -> None:
        """(A AND B) OR (C AND D) should parse correctly."""
        query = "(tag:a > 0.5 AND tag:b > 0.6) OR (tag:c > 0.7 AND tag:d > 0.8)"
        result = parse_smart_playlist_query(query)

        # Root should be OR with two nested groups
        assert result.root.logic == "OR"
        assert len(result.root.groups) == 2
        assert len(result.root.conditions) == 0

        # Both nested groups should be AND
        for group in result.root.groups:
            assert group.logic == "AND"
            assert len(group.conditions) == 2

    @pytest.mark.unit
    def test_triple_nesting(self) -> None:
        """((A AND B) OR C) AND D should parse correctly."""
        query = "((tag:a > 0.5 AND tag:b > 0.6) OR tag:c > 0.7) AND tag:d > 0.8"
        result = parse_smart_playlist_query(query)

        # Root should be AND
        assert result.root.logic == "AND"
        # Should have one nested group and one direct condition
        assert len(result.root.groups) == 1
        assert len(result.root.conditions) == 1
        # Verify condition tag_key includes namespace
        assert result.root.conditions[0].tag_key == "nom:d"

    @pytest.mark.unit
    def test_depth_property_calculation(self) -> None:
        """RuleGroup.depth should correctly calculate max nesting depth."""
        # Build nested structure manually
        inner = RuleGroup(logic="AND", conditions=[], groups=[])
        for _ in range(3):
            inner = RuleGroup(logic="OR", conditions=[], groups=[inner])

        assert inner.depth == 4  # 1 base + 3 nestings


class TestBackwardCompatibility:
    """P1-S6: Flat queries should parse as single group."""

    @pytest.mark.unit
    def test_simple_and_query(self) -> None:
        """Simple AND query should parse as root AND group."""
        query = "tag:mood > 0.5 AND tag:energy > 0.6"
        result = parse_smart_playlist_query(query)

        assert result.root.logic == "AND"
        assert len(result.root.conditions) == 2
        assert len(result.root.groups) == 0
        # is_simple_and is a property, not a method
        assert result.is_simple_and

    @pytest.mark.unit
    def test_simple_or_query(self) -> None:
        """Simple OR query should parse as root OR group."""
        query = "tag:mood > 0.5 OR tag:energy > 0.6"
        result = parse_smart_playlist_query(query)

        assert result.root.logic == "OR"
        assert len(result.root.conditions) == 2
        assert len(result.root.groups) == 0
        # is_simple_or is a property, not a method
        assert result.is_simple_or

    @pytest.mark.unit
    def test_single_condition(self) -> None:
        """Single condition should parse as root AND group."""
        query = "tag:mood > 0.5"
        result = parse_smart_playlist_query(query)

        assert result.root.logic == "AND"
        assert len(result.root.conditions) == 1
        assert len(result.root.groups) == 0

    @pytest.mark.unit
    def test_multiple_and_conditions(self) -> None:
        """Multiple AND conditions should parse flat."""
        query = "tag:a > 0.5 AND tag:b > 0.6 AND tag:c > 0.7"
        result = parse_smart_playlist_query(query)

        assert result.root.logic == "AND"
        assert len(result.root.conditions) == 3
        assert len(result.root.groups) == 0
