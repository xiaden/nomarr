"""Unit tests for nomarr.helpers.exceptions module.

Tests custom exception classes.
"""

import pytest

from nomarr.helpers.exceptions import PlaylistQueryError


class TestPlaylistQueryError:
    """Tests for PlaylistQueryError exception."""

    @pytest.mark.unit
    def test_playlist_query_error_is_exception(self) -> None:
        """PlaylistQueryError should be an Exception subclass."""
        assert issubclass(PlaylistQueryError, Exception)

    @pytest.mark.unit
    def test_playlist_query_error_can_be_raised(self) -> None:
        """PlaylistQueryError should be raisable with a message."""
        with pytest.raises(PlaylistQueryError, match="invalid query"):
            raise PlaylistQueryError("invalid query")

    @pytest.mark.unit
    def test_playlist_query_error_stores_message(self) -> None:
        """PlaylistQueryError should store the error message."""
        error = PlaylistQueryError("test message")
        assert str(error) == "test message"

    @pytest.mark.unit
    def test_playlist_query_error_can_be_caught_as_exception(self) -> None:
        """PlaylistQueryError should be catchable as generic Exception."""
        try:
            raise PlaylistQueryError("test")
        except Exception as e:
            assert isinstance(e, PlaylistQueryError)
