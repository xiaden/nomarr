"""
Unit tests for persistence layer operator validation.

Tests cover:
- Valid operators are accepted
- Invalid operators are rejected
- SQL injection attempts are blocked
"""

import sqlite3

import pytest

from nomarr.persistence.database.joined_queries_sql import JoinedQueryOperations


class TestOperatorValidation:
    """Test operator whitelist enforcement in get_file_ids_matching_tag."""

    @pytest.fixture
    def ops(self):
        """Create JoinedQueryOperations with in-memory database."""
        conn = sqlite3.connect(":memory:")
        # Create minimal schema for testing
        conn.execute("""
            CREATE TABLE file_tags (
                file_id INTEGER,
                tag_key TEXT,
                tag_value TEXT
            )
        """)
        conn.execute("""
            INSERT INTO file_tags VALUES
                (1, 'nom:mood_happy', '0.8'),
                (2, 'nom:mood_happy', '0.6'),
                (3, 'nom:mood_happy', '0.9')
        """)
        conn.commit()
        return JoinedQueryOperations(conn)

    def test_greater_than_operator(self, ops):
        """Test > operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", ">", 0.7)
        assert isinstance(result, set)
        assert len(result) == 2  # Files 1 and 3 (0.8 and 0.9)

    def test_less_than_operator(self, ops):
        """Test < operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", "<", 0.7)
        assert isinstance(result, set)
        assert len(result) == 1  # File 2 (0.6)

    def test_greater_or_equal_operator(self, ops):
        """Test >= operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", ">=", 0.8)
        assert isinstance(result, set)
        assert len(result) == 2  # Files 1 and 3 (0.8 and 0.9)

    def test_less_or_equal_operator(self, ops):
        """Test <= operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", "<=", 0.8)
        assert isinstance(result, set)
        assert len(result) == 2  # Files 1 and 2 (0.8 and 0.6)

    def test_equals_operator(self, ops):
        """Test = operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", "=", 0.8)
        assert isinstance(result, set)
        assert len(result) == 1  # File 1 (0.8)

    def test_not_equals_operator(self, ops):
        """Test != operator is accepted."""
        result = ops.get_file_ids_matching_tag("nom:mood_happy", "!=", 0.8)
        assert isinstance(result, set)
        assert len(result) == 2  # Files 2 and 3 (not 0.8)

    def test_invalid_operator_rejected(self, ops):
        """Test that invalid operators are rejected."""
        with pytest.raises(ValueError, match="Invalid operator"):
            ops.get_file_ids_matching_tag("nom:mood_happy", "LIKE", 0.7)

    def test_sql_injection_attempt_blocked(self, ops):
        """Test that SQL injection attempts are blocked."""
        with pytest.raises(ValueError, match="Invalid operator"):
            ops.get_file_ids_matching_tag("nom:mood_happy", "; DROP TABLE file_tags; --", 0.7)

    def test_another_sql_injection_attempt(self, ops):
        """Test another SQL injection pattern is blocked."""
        with pytest.raises(ValueError, match="Invalid operator"):
            ops.get_file_ids_matching_tag("nom:mood_happy", "= 1 OR 1=1 --", 0.7)

    def test_non_whitelisted_comparison(self, ops):
        """Test that non-whitelisted comparisons are rejected."""
        with pytest.raises(ValueError, match="Invalid operator"):
            ops.get_file_ids_matching_tag("nom:mood_happy", "IS NOT", 0.7)
