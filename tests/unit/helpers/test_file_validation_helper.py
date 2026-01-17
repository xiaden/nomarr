"""
Unit tests for nomarr.helpers.file_validation_helper module.

Tests file validation and skip logic utilities.
Note: These tests mock filesystem and mutagen operations to remain local-safe.
"""

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.file_validation_helper import (
    check_already_tagged,
    make_skip_result,
    should_skip_processing,
    validate_file_exists,
)


class TestValidateFileExists:
    """Tests for validate_file_exists function."""

    @pytest.mark.unit
    def test_raises_for_nonexistent_file(self) -> None:
        """Should raise RuntimeError for non-existent file."""
        with patch("pathlib.Path.exists", return_value=False):
            with pytest.raises(RuntimeError, match="File not found"):
                validate_file_exists("/nonexistent/file.mp3")

    @pytest.mark.unit
    def test_raises_for_directory(self) -> None:
        """Should raise RuntimeError if path is a directory."""
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.is_file", return_value=False):
            with pytest.raises(RuntimeError, match="Not a file"):
                validate_file_exists("/some/directory")

    @pytest.mark.unit
    def test_raises_for_unreadable_file(self) -> None:
        """Should raise RuntimeError if file is not readable."""
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.is_file", return_value=True):
            with patch("os.access", return_value=False):
                with pytest.raises(RuntimeError, match="File not readable"):
                    validate_file_exists("/unreadable/file.mp3")

    @pytest.mark.unit
    def test_succeeds_for_valid_file(self) -> None:
        """Should not raise for valid, readable file."""
        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.is_file", return_value=True):
            with patch("os.access", return_value=True):
                # Should not raise
                validate_file_exists("/valid/file.mp3")


class TestCheckAlreadyTagged:
    """Tests for check_already_tagged function."""

    @pytest.mark.unit
    def test_returns_false_when_no_audio_file(self) -> None:
        """Should return False when mutagen can't open file."""
        with patch("mutagen._file.File", return_value=None):
            result = check_already_tagged(
                path="/test.mp3",
                namespace="nom-music",
                version_tag_key="version",
                current_version="1.0.0",
            )
            assert result is False

    @pytest.mark.unit
    def test_returns_false_when_no_tags(self) -> None:
        """Should return False when file has no tags."""
        mock_audio = MagicMock()
        mock_audio.tags = None

        with patch("mutagen._file.File", return_value=mock_audio):
            result = check_already_tagged(
                path="/test.mp3",
                namespace="nom-music",
                version_tag_key="version",
                current_version="1.0.0",
            )
            assert result is False

    @pytest.mark.unit
    def test_returns_false_on_exception(self) -> None:
        """Should return False when exception occurs."""
        with patch(
            "mutagen._file.File",
            side_effect=Exception("Test error"),
        ):
            result = check_already_tagged(
                path="/test.mp3",
                namespace="nom-music",
                version_tag_key="version",
                current_version="1.0.0",
            )
            assert result is False


class TestShouldSkipProcessing:
    """Tests for should_skip_processing function."""

    @pytest.mark.unit
    def test_never_skips_when_force_true(self) -> None:
        """Should never skip when force=True."""
        # No mocking needed - force should short-circuit
        should_skip, reason = should_skip_processing(
            path="/test.mp3",
            force=True,
            namespace="nom-music",
            version_tag_key="version",
            tagger_version="1.0.0",
        )
        assert should_skip is False
        assert reason is None

    @pytest.mark.unit
    def test_skips_when_already_tagged(self) -> None:
        """Should skip when file already has correct version tag."""
        with patch(
            "nomarr.helpers.file_validation_helper.check_already_tagged",
            return_value=True,
        ):
            should_skip, reason = should_skip_processing(
                path="/test.mp3",
                force=False,
                namespace="nom-music",
                version_tag_key="version",
                tagger_version="1.0.0",
            )
            assert should_skip is True
            assert reason == "already_tagged_v1.0.0"

    @pytest.mark.unit
    def test_does_not_skip_when_not_tagged(self) -> None:
        """Should not skip when file is not tagged."""
        with patch(
            "nomarr.helpers.file_validation_helper.check_already_tagged",
            return_value=False,
        ):
            should_skip, reason = should_skip_processing(
                path="/test.mp3",
                force=False,
                namespace="nom-music",
                version_tag_key="version",
                tagger_version="1.0.0",
            )
            assert should_skip is False
            assert reason is None


class TestMakeSkipResult:
    """Tests for make_skip_result function."""

    @pytest.mark.unit
    def test_creates_standard_format(self) -> None:
        """Should create result matching process_file output format."""
        result = make_skip_result("/test.mp3", "already_tagged_v1.0.0")

        assert result["file"] == "/test.mp3"
        assert result["elapsed"] == 0.0
        assert result["duration"] == 0.0
        assert result["heads_processed"] == 0
        assert result["tags_written"] == 0
        assert result["skipped"] is True
        assert result["skip_reason"] == "already_tagged_v1.0.0"
        assert result["tags"] == {}

    @pytest.mark.unit
    def test_includes_all_required_keys(self) -> None:
        """Should include all keys expected by consumers."""
        result = make_skip_result("/test.mp3", "test_reason")

        required_keys = {
            "file",
            "elapsed",
            "duration",
            "heads_processed",
            "tags_written",
            "skipped",
            "skip_reason",
            "tags",
        }
        assert set(result.keys()) == required_keys

    @pytest.mark.unit
    def test_accepts_any_skip_reason(self) -> None:
        """Should accept arbitrary skip reason strings."""
        result = make_skip_result("/test.mp3", "custom_reason_123")
        assert result["skip_reason"] == "custom_reason_123"
