"""Tests for safe_write_comp - atomic tag writing with audio sanity verification."""

from pathlib import Path
from unittest.mock import patch

from nomarr.components.tagging.safe_write_comp import (
    SafeWriteResult,
    _AudioProperties,
    safe_write_tags,
)
from nomarr.helpers.dto.path_dto import LibraryPath

_GOOD_PROPS = _AudioProperties(duration=180.0, sample_rate=44100, channels=2)


class TestSafeWriteVerification:
    """Tests that audio property sanity check is always performed."""

    def test_audio_properties_verified_on_success(self, tmp_path: Path) -> None:
        """Audio properties are probed and compared for every write."""
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
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties"
        ) as mock_probe:
            mock_probe.return_value = _GOOD_PROPS

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            # Probed twice: original before copy, temp after write
            assert mock_probe.call_count == 2
            assert result.success is True

    def test_duration_mismatch_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when duration differs beyond tolerance after write."""
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

        truncated_props = _AudioProperties(duration=10.0, sample_rate=44100, channels=2)

        with patch(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties"
        ) as mock_probe:
            mock_probe.side_effect = [_GOOD_PROPS, truncated_props]

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            assert result.success is False
            assert "Duration changed" in (result.error or "")

    def test_sample_rate_mismatch_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when sample rate changes after write."""
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

        wrong_sr_props = _AudioProperties(duration=180.0, sample_rate=22050, channels=2)

        with patch(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties"
        ) as mock_probe:
            mock_probe.side_effect = [_GOOD_PROPS, wrong_sr_props]

            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, mock_write_fn, mtime_ms)

            assert result.success is False
            assert "Sample rate changed" in (result.error or "")

    def test_probe_failure_on_original_returns_failure(self, tmp_path: Path) -> None:
        """Returns failure when the original file cannot be probed."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"not a real audio file")

        library_path = LibraryPath(
            relative="test.mp3",
            absolute=test_file,
            library_id="test_lib",
            status="valid",
        )

        with patch(
            "nomarr.components.tagging.safe_write_comp._probe_audio_properties",
            side_effect=RuntimeError("mutagen could not read audio file"),
        ):
            mtime_ms = int(test_file.stat().st_mtime * 1000)
            result = safe_write_tags(library_path, tmp_path, lambda _: None, mtime_ms)

            assert result.success is False
            assert "Failed to probe original file" in (result.error or "")


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
