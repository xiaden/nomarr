"""
Unit tests for nomarr.helpers.time_helper module.

Tests the time utility functions.
"""

import pytest

from nomarr.helpers.time_helper import Milliseconds, now_ms


class TestNowMs:
    """Tests for now_ms function."""

    @pytest.mark.unit
    def test_now_ms_returns_milliseconds_type(self) -> None:
        """now_ms should return a Milliseconds dataclass."""
        result = now_ms()
        assert isinstance(result, Milliseconds)

    @pytest.mark.unit
    def test_now_ms_value_is_integer(self) -> None:
        """now_ms.value should be an integer."""
        result = now_ms()
        assert isinstance(result.value, int)

    @pytest.mark.unit
    def test_now_ms_returns_positive_value(self) -> None:
        """now_ms should return a positive timestamp."""
        result = now_ms()
        assert result.value > 0

    @pytest.mark.unit
    def test_now_ms_is_reasonable_timestamp(self) -> None:
        """now_ms should return a timestamp in milliseconds (roughly current epoch)."""
        result = now_ms()
        # Should be after year 2020 (1577836800000 ms) and before year 2100
        assert result.value > 1577836800000
        assert result.value < 4102444800000

    @pytest.mark.unit
    def test_now_ms_increases_over_time(self) -> None:
        """Consecutive calls to now_ms should return non-decreasing values."""
        first = now_ms()
        second = now_ms()
        assert second.value >= first.value
