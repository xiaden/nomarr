"""Tests for nomarr.components.library.file_batch_scanner_comp module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.file_batch_scanner_comp import (
    _compute_normalized_path,
    scan_folder_files,
)
from nomarr.helpers.time_helper import Milliseconds

MODULE = "nomarr.components.library.file_batch_scanner_comp"


def _make_audio_file(path: Path) -> Path:
    """Create a minimal audio file placeholder on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake-audio")
    return path


def _make_valid_library_path(absolute_path: Path) -> MagicMock:
    """Build a valid library-path-like mock for scanner tests."""
    library_path = MagicMock()
    library_path.is_valid.return_value = True
    library_path.absolute = absolute_path
    library_path.reason = None
    return library_path


def _make_invalid_library_path(reason: str = "invalid path") -> MagicMock:
    """Build an invalid library-path-like mock for scanner tests."""
    library_path = MagicMock()
    library_path.is_valid.return_value = False
    library_path.absolute = None
    library_path.reason = reason
    return library_path


class TestComputeNormalizedPath:
    """Tests for _compute_normalized_path."""

    @pytest.mark.unit
    def test_returns_posix_relative_path(self, tmp_path: Path) -> None:
        library_root = tmp_path / "music"
        track_path = library_root / "Rock" / "song.mp3"

        result = _compute_normalized_path(track_path, library_root)

        assert result == "Rock/song.mp3"

    @pytest.mark.unit
    def test_raises_value_error_for_file_outside_library_root(self, tmp_path: Path) -> None:
        library_root = tmp_path / "music"
        outside_path = tmp_path / "elsewhere" / "song.mp3"

        with pytest.raises(ValueError):
            _compute_normalized_path(outside_path, library_root)


class TestScanFolderFiles:
    """Tests for scan_folder_files."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_result_when_folder_cannot_be_read(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        folder_path = tmp_path / "missing"
        library_root = tmp_path / "music"

        with patch(f"{MODULE}.os.listdir", side_effect=OSError("denied")):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="missing",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={},
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.metadata_map == {}
        assert result.discovered_paths == set()
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 0}
        assert result.warnings == []
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_unchanged_existing_file_without_extracting_metadata(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")
        modified_time = int(track_path.stat().st_mtime * 1000)

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.extract_metadata") as mock_extract_metadata,
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={str(track_path): {"modified_time": modified_time}},
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.metadata_map == {}
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 1}
        assert result.edge_bootstraps == []
        mock_extract_metadata.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_invalid_path_as_failed(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_invalid_library_path("path not allowed"),
            ),
            patch(f"{MODULE}.extract_metadata") as mock_extract_metadata,
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={},
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.metadata_map == {}
        assert result.discovered_paths == set()
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 1, "files_skipped": 0}
        assert result.warnings == [f"Invalid path: {track_path} - path not allowed"]
        mock_extract_metadata.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_file_outside_library_root_as_failed(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        _make_audio_file(folder_path / "song.mp3")
        outside_path = tmp_path / "elsewhere" / "song.mp3"

        with patch(
            f"{MODULE}.build_library_path_from_input",
            return_value=_make_valid_library_path(outside_path),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={},
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.metadata_map == {}
        assert result.discovered_paths == set()
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 1, "files_skipped": 0}
        assert result.warnings == [f"File outside library root: {outside_path}"]
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_adds_new_file_and_scan_skipped_edge_for_short_duration(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        metadata = {
            "duration": 12,
            "title": "Song Title",
            "nom_tags": {},
        }

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.extract_metadata", return_value=metadata),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(1234567890)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={},
                tagger_version="suite-v1",
                db=mock_db,
                min_duration_s=30,
            )

        assert len(result.file_entries) == 1
        entry = result.file_entries[0]
        assert entry["path"] == str(track_path)
        assert entry["normalized_path"] == "Rock/song.mp3"
        assert entry["library_id"] == "libraries/1"
        assert entry["duration_seconds"] == 12
        assert entry["title"] == "Song Title"
        assert entry["scanned_at"] == 1234567890
        assert result.metadata_map == {str(track_path): metadata}
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == {str(track_path)}
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 0}
        assert result.warnings == []
        assert result.edge_bootstraps == [
            {
                "normalized_path": "Rock/song.mp3",
                "type": "ml_tagged",
                "version": "scan_skipped",
            }
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_changed_currently_tagged_file_as_updated_with_version_edge(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        metadata = {
            "duration": 180,
            "title": "Song Title",
            "nom_tags": {"nom_version": "suite-v1"},
        }

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.extract_metadata", return_value=metadata),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(987654321)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={
                    str(track_path): {
                        "modified_time": 0,
                        "tagged": True,
                    }
                },
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert len(result.file_entries) == 1
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 1, "files_failed": 0, "files_skipped": 0}
        assert result.edge_bootstraps == [
            {
                "normalized_path": "Rock/song.mp3",
                "type": "ml_tagged",
                "version": "suite-v1",
            }
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_records_warning_when_metadata_extraction_fails(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.extract_metadata", side_effect=RuntimeError("boom")),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                folder_rel_path="Rock",
                library_root=library_root,
                library_id="libraries/1",
                existing_files={},
                tagger_version="suite-v1",
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.metadata_map == {}
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 1, "files_skipped": 0}
        assert len(result.warnings) == 1
        assert result.warnings[0].startswith(f"Extraction failed: {track_path} - boom")
        assert result.edge_bootstraps == []
