"""Tests for nomarr.components.library.file_batch_scanner_comp module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.file_batch_scanner_comp import (
    _compute_normalized_path,
    scan_folder_files,
)
from nomarr.components.library.song_query_types import StateTaggedSong
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.time_helper import Milliseconds

if TYPE_CHECKING:
    from pathlib import Path

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


def _state_tagged(
    *, modified_time: int, tagged: bool = False, normalized_path: str = "Rock/song.mp3"
) -> StateTaggedSong:
    """Build a typed folder carrier as the scan workflows now provide it."""
    library = LibraryIdentity(library_uuid="uuid-lib", name="lib", root_path="/music")
    return StateTaggedSong(
        candidate=SongStateCandidate(
            identity=SongIdentity(library=library, normalized_path=normalized_path),
            song=Song(
                path=f"/music/{normalized_path}",
                normalized_path=normalized_path,
                file_size=100,
                modified_time=modified_time,
                duration_seconds=None,
                chromaprint=None,
                needs_tagging=False,
                is_valid=True,
                tagged=tagged,
                calibration_hash=None,
                write_claimed_by=None,
                last_tagged_at=None,
                scanned_at=None,
                created_at=modified_time,
            ),
            states=("processed",) if tagged else (),
        ),
        has_tagged_state=tagged,
    )


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
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.file_entries == []
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

        with patch(
            f"{MODULE}.build_library_path_from_input",
            return_value=_make_valid_library_path(track_path),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={str(track_path): _state_tagged(modified_time=modified_time)},
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 1}
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_invalid_path_as_failed(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with patch(
            f"{MODULE}.build_library_path_from_input",
            return_value=_make_invalid_library_path("path not allowed"),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.discovered_paths == set()
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 1, "files_skipped": 0}
        assert result.warnings == [f"Invalid path: {track_path} - path not allowed"]

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
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.discovered_paths == set()
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 1, "files_skipped": 0}
        assert result.warnings == [f"File outside library root: {outside_path}"]
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_adds_new_file_entry_with_file_stats(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(1234567890)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert len(result.file_entries) == 1
        entry = result.file_entries[0]
        assert entry["path"] == str(track_path)
        assert entry["normalized_path"] == "Rock/song.mp3"
        assert "library_id" not in entry
        assert entry["scanned_at"] == 1234567890
        assert "duration_seconds" not in entry
        assert "title" not in entry
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == {str(track_path)}
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 0}
        assert result.warnings == []
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_marks_changed_tagged_carrier_as_updated_without_bootstrap_edges(self, tmp_path: Path) -> None:
        """A changed, already-tagged typed carrier is updated; the retired version
        bootstrap emits no edge.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(987654321)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={str(track_path): _state_tagged(modified_time=0, tagged=True)},
                db=mock_db,
            )

        assert len(result.file_entries) == 1
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 1, "files_failed": 0, "files_skipped": 0}
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_preserves_discovery_order_across_multiple_files(self, tmp_path: Path) -> None:
        """Multiple discovered files must keep the disk-listing order in file_entries.

        The scan workflow relies on ``file_entries`` staying aligned with the typed
        identities returned by ``upsert_scanned_files`` (``zip(..., strict=True)``), so
        the scanner must not reorder or deduplicate across files.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        names = ["a.mp3", "b.mp3", "c.mp3"]
        for name in names:
            _make_audio_file(folder_path / name)
        expected_paths = [str(folder_path / name) for name in names]

        from pathlib import Path as RuntimePath

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                side_effect=lambda path, _db: _make_valid_library_path(RuntimePath(path)),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(111)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert [entry["path"] for entry in result.file_entries] == expected_paths
        assert [entry["normalized_path"] for entry in result.file_entries] == [f"Rock/{name}" for name in names]
        assert result.discovered_paths == set(expected_paths)
        assert result.new_file_paths == set(expected_paths)
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 0}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rejects_raw_row_shaped_existing_files(self, tmp_path: Path) -> None:
        """The scanner boundary accepts typed ``StateTaggedSong`` carriers only.

        Raw row/dict scan entries are no longer representable; passing one must not
        silently work. This pins the hard cut so a future change cannot reintroduce a
        raw-document path at this boundary.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            pytest.raises(AttributeError),
        ):
            scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={str(track_path): {"modified_time": 0}},
                db=mock_db,
            )
