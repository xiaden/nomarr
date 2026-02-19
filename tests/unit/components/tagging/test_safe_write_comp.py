"""Tests for safe_write_comp - atomic tag writing with optional verification."""

from pathlib import Path
from unittest.mock import patch

from nomarr.components.tagging.safe_write_comp import (
    SafeWriteResult,
    _safe_write_fallback,
    _safe_write_hardlink,
    safe_write_tags,
)
from nomarr.helpers.dto.path_dto import LibraryPath


class TestSafeWriteTagsVerifyAudio:
    """Tests for verify_audio parameter behavior."""

    def test_default_verify_audio_is_true(self) -> None:
        """verify_audio defaults to True for backward compatibility."""
        # Introspect the function signature
        import inspect

        sig = inspect.signature(safe_write_tags)
        verify_audio_param = sig.parameters.get("verify_audio")
        assert verify_audio_param is not None
        assert verify_audio_param.default is True

    def test_verify_audio_false_skips_chromaprint(self, tmp_path: Path) -> None:
        """When verify_audio=False, chromaprint computation is skipped."""
        # Create a temp file to write to
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio content")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        write_fn_called = [False]

        def mock_write_fn(temp_path: Path) -> None:
            write_fn_called[0] = True
            # Just touch the file - simulate tag write
            temp_path.touch()

        with patch(
            "nomarr.components.tagging.safe_write_comp._compute_chromaprint_for_path"
        ) as mock_chromaprint:
            # With verify_audio=False, chromaprint should NOT be called
            result = safe_write_tags(
                library_path,
                tmp_path,
                "original_chromaprint_value",
                mock_write_fn,
                verify_audio=False,
            )

            # The chromaprint function should not be called
            mock_chromaprint.assert_not_called()
            assert write_fn_called[0] is True
            assert result.success is True

    def test_verify_audio_true_calls_chromaprint(self, tmp_path: Path) -> None:
        """When verify_audio=True (default), chromaprint is computed and verified."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio content")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        def mock_write_fn(temp_path: Path) -> None:
            temp_path.touch()

        with patch(
            "nomarr.components.tagging.safe_write_comp._compute_chromaprint_for_path"
        ) as mock_chromaprint:
            # Return same chromaprint to simulate no corruption
            mock_chromaprint.return_value = "original_chromaprint_value"

            result = safe_write_tags(
                library_path,
                tmp_path,
                "original_chromaprint_value",
                mock_write_fn,
                verify_audio=True,  # explicit True
            )

            # Chromaprint should be called for verification
            mock_chromaprint.assert_called_once()
            assert result.success is True


class TestSafeWriteHardlinkVerifyAudio:
    """Tests for _safe_write_hardlink verify_audio parameter."""

    def test_verify_audio_false_skips_chromaprint(self, tmp_path: Path) -> None:
        """Hardlink path skips chromaprint when verify_audio=False."""
        # Create source file
        original = tmp_path / "original.mp3"
        original.write_bytes(b"audio data")

        temp_folder = tmp_path / "temp"
        temp_folder.mkdir()

        def mock_write_fn(temp_path: Path) -> None:
            pass

        with patch(
            "nomarr.components.tagging.safe_write_comp._compute_chromaprint_for_path"
        ) as mock_chromaprint:
            result = _safe_write_hardlink(
                original,
                temp_folder,
                "original.mp3",
                "some_chromaprint",
                mock_write_fn,
                verify_audio=False,
            )

            mock_chromaprint.assert_not_called()
            assert result.success is True


class TestSafeWriteFallbackVerifyAudio:
    """Tests for _safe_write_fallback verify_audio parameter."""

    def test_verify_audio_false_skips_chromaprint(self, tmp_path: Path) -> None:
        """Fallback path skips chromaprint when verify_audio=False."""
        original = tmp_path / "original.mp3"
        original.write_bytes(b"audio data")

        def mock_write_fn(temp_path: Path) -> None:
            pass

        with patch(
            "nomarr.components.tagging.safe_write_comp._compute_chromaprint_for_path"
        ) as mock_chromaprint:
            result = _safe_write_fallback(
                original,
                "some_chromaprint",
                mock_write_fn,
                verify_audio=False,
            )

            mock_chromaprint.assert_not_called()
            assert result.success is True


class TestSafeWriteResult:
    """Tests for SafeWriteResult dataclass."""

    def test_success_result(self) -> None:
        """Can create a success result."""
        result = SafeWriteResult(success=True)
        assert result.success is True
        assert result.error is None

    def test_failure_result(self) -> None:
        """Can create a failure result with error message."""
        result = SafeWriteResult(success=False, error="Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
