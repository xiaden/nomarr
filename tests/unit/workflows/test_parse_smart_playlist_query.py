"""
Unit tests for smart playlist query parser.

Tests cover:
- Pure AND queries
- Pure OR queries
- Mixed AND/OR queries (should be rejected)
- Invalid syntax
- Edge cases
"""

import pytest

from nomarr.helpers.exceptions import PlaylistQueryError
from nomarr.workflows.navidrome.parse_smart_playlist_query import (
    parse_smart_playlist_query,
)


class TestPureANDQueries:
    """Test queries with only AND operators."""

    def test_single_condition(self):
        """Single condition should be treated as AND."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7")

        assert len(result.all_conditions) == 1
        assert len(result.any_conditions) == 0
        assert result.is_simple_and

        cond = result.all_conditions[0]
        assert cond.tag_key == "nom:mood_happy"
        assert cond.operator == ">"
        assert cond.value == 0.7

    def test_two_and_conditions(self):
        """Two conditions with AND."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7 AND tag:energy > 0.6")

        assert len(result.all_conditions) == 2
        assert len(result.any_conditions) == 0
        assert result.is_simple_and

    def test_three_and_conditions(self):
        """Three conditions with AND."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7 AND tag:energy > 0.6 AND tag:bpm > 120")

        assert len(result.all_conditions) == 3
        assert len(result.any_conditions) == 0


class TestPureORQueries:
    """Test queries with only OR operators."""

    def test_two_or_conditions(self):
        """Two conditions with OR."""
        result = parse_smart_playlist_query("tag:genre = Rock OR tag:genre = Metal")

        assert len(result.all_conditions) == 0
        assert len(result.any_conditions) == 2
        assert result.is_simple_or

    def test_three_or_conditions(self):
        """Three conditions with OR."""
        result = parse_smart_playlist_query("tag:genre = Rock OR tag:genre = Metal OR tag:genre = Pop")

        assert len(result.all_conditions) == 0
        assert len(result.any_conditions) == 3


class TestMixedLogic:
    """Test queries with mixed AND/OR operators (should be rejected)."""

    def test_and_then_or(self):
        """Mixed AND followed by OR should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Mixed AND/OR operators are not supported"):
            parse_smart_playlist_query("tag:mood_happy > 0.7 AND tag:energy > 0.6 OR tag:bpm > 120")

    def test_or_then_and(self):
        """Mixed OR followed by AND should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Mixed AND/OR operators are not supported"):
            parse_smart_playlist_query("tag:genre = Rock OR tag:genre = Metal AND tag:bpm > 120")


class TestInvalidSyntax:
    """Test queries with invalid syntax."""

    def test_empty_query(self):
        """Empty query should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Query cannot be empty"):
            parse_smart_playlist_query("")

    def test_whitespace_only(self):
        """Whitespace-only query should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Query cannot be empty"):
            parse_smart_playlist_query("   ")

    def test_invalid_condition_syntax(self):
        """Invalid condition format should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Invalid condition syntax"):
            parse_smart_playlist_query("invalid syntax")

    def test_missing_tag_prefix(self):
        """Condition without 'tag:' prefix should be rejected."""
        with pytest.raises(PlaylistQueryError, match="Invalid condition syntax"):
            parse_smart_playlist_query("mood_happy > 0.7")

    def test_query_too_long(self):
        """Query exceeding MAX_QUERY_LENGTH should be rejected."""
        long_query = "tag:x > 0.7" + (" AND tag:x > 0.7" * 500)
        with pytest.raises(PlaylistQueryError, match="Query too long"):
            parse_smart_playlist_query(long_query)


class TestOperators:
    """Test various comparison operators."""

    def test_greater_than(self):
        """Test > operator."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7")
        assert result.all_conditions[0].operator == ">"

    def test_less_than(self):
        """Test < operator."""
        result = parse_smart_playlist_query("tag:energy < 0.3")
        assert result.all_conditions[0].operator == "<"

    def test_greater_or_equal(self):
        """Test >= operator."""
        result = parse_smart_playlist_query("tag:bpm >= 120")
        assert result.all_conditions[0].operator == ">="

    def test_less_or_equal(self):
        """Test <= operator."""
        result = parse_smart_playlist_query("tag:bpm <= 140")
        assert result.all_conditions[0].operator == "<="

    def test_equals(self):
        """Test = operator."""
        result = parse_smart_playlist_query("tag:genre = Rock")
        assert result.all_conditions[0].operator == "="

    def test_not_equals(self):
        """Test != operator."""
        result = parse_smart_playlist_query("tag:genre != Classical")
        assert result.all_conditions[0].operator == "!="

    def test_contains(self):
        """Test contains operator."""
        result = parse_smart_playlist_query("tag:artist contains Beatles")
        assert result.all_conditions[0].operator == "contains"


class TestValueTypes:
    """Test value parsing for different types."""

    def test_float_value(self):
        """Float values should be parsed correctly."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7")
        assert isinstance(result.all_conditions[0].value, float)
        assert result.all_conditions[0].value == 0.7

    def test_integer_value(self):
        """Integer values should be parsed correctly."""
        result = parse_smart_playlist_query("tag:bpm > 120")
        assert isinstance(result.all_conditions[0].value, int)
        assert result.all_conditions[0].value == 120

    def test_string_value(self):
        """String values should be preserved."""
        result = parse_smart_playlist_query("tag:genre = Rock")
        assert isinstance(result.all_conditions[0].value, str)
        assert result.all_conditions[0].value == "Rock"

    def test_quoted_string_value(self):
        """Quoted strings should have quotes removed."""
        result = parse_smart_playlist_query('tag:artist = "The Beatles"')
        assert result.all_conditions[0].value == "The Beatles"


class TestNamespace:
    """Test namespace handling."""

    def test_default_namespace(self):
        """Default namespace should be 'nom'."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7")
        assert result.all_conditions[0].tag_key == "nom:mood_happy"

    def test_custom_namespace(self):
        """Custom namespace should be applied."""
        result = parse_smart_playlist_query("tag:mood_happy > 0.7", namespace="essentia")
        assert result.all_conditions[0].tag_key == "essentia:mood_happy"

    def test_explicit_namespace_in_query(self):
        """Explicit namespace in query is prepended with default namespace."""
        result = parse_smart_playlist_query("tag:essentia:mood_happy > 0.7", namespace="nom")
        # Parser always prepends the default namespace, even when key contains colons
        assert result.all_conditions[0].tag_key == "nom:essentia:mood_happy"
