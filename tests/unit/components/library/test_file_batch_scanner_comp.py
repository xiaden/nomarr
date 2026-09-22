"""Tests for nomarr.components.library.file_batch_scanner_comp module."""

from __future__ import annotations

import errno
import os
from pathlib import Path
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

MODULE = "nomarr.components.library.file_batch_scanner_comp"


def _stat_raising_for(target: Path, error: OSError) -> object:
    """Wrap the real ``os.stat`` so it raises ``error`` for ``target`` only."""
    real_stat = os.stat

    def _stat(path: object, *args: object, **kwargs: object) -> object:
        if os.fspath(path) == str(target):  # type: ignore[arg-type]
            raise error
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    return _stat


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
    *, modified_time: int, file_size: int = 100, tagged: bool = False, normalized_path: str = "Rock/song.mp3"
) -> StateTaggedSong:
    """Build a typed folder carrier as the scan workflows now provide it."""
    library = LibraryIdentity(library_uuid="uuid-lib", name="lib", root_path="/music")
    return StateTaggedSong(
        candidate=SongStateCandidate(
            identity=SongIdentity(library=library, normalized_path=normalized_path),
            song=Song(
                path=f"/music/{normalized_path}",
                normalized_path=normalized_path,
                file_size=file_size,
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
    def test_raises_when_folder_cannot_be_read(self, tmp_path: Path) -> None:
        mock_db = MagicMock()
        folder_path = tmp_path / "missing"
        library_root = tmp_path / "music"

        with (
            patch(f"{MODULE}.os.listdir", side_effect=OSError("denied")),
            pytest.raises(OSError, match="denied"),
        ):
            scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_legitimately_empty_folder_returns_successful_empty_result(self, tmp_path: Path) -> None:
        """A folder that is readable but contains no audio files remains a successful
        empty result: the correct counterpart to ``test_raises_when_folder_cannot_be_read``.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "empty"
        folder_path.mkdir(parents=True)

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
                existing_files={
                    str(track_path): _state_tagged(
                        modified_time=modified_time,
                        file_size=track_path.stat().st_size,
                    )
                },
                db=mock_db,
            )

        assert result.file_entries == []
        assert result.discovered_paths == {str(track_path)}
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 0, "files_failed": 0, "files_skipped": 1}
        assert result.edge_bootstraps == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_size_only_change_with_same_mtime_is_updated(self, tmp_path: Path) -> None:
        """A file whose content changed but whose mtime is unchanged must not be
        skipped: a differing on-disk size is a content change that follows
        modified-file invalidation (metadata update + hydration reset)."""
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        track_path = _make_audio_file(folder_path / "song.mp3")
        modified_time = int(track_path.stat().st_mtime * 1000)
        on_disk_size = track_path.stat().st_size

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                return_value=_make_valid_library_path(track_path),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(555)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={
                    str(track_path): _state_tagged(
                        modified_time=modified_time,
                        file_size=on_disk_size - 1,
                    )
                },
                db=mock_db,
            )

        assert len(result.file_entries) == 1
        entry = result.file_entries[0]
        assert entry["path"] == str(track_path)
        assert entry["modified_time"] == modified_time
        assert entry["file_size"] == on_disk_size
        assert result.new_file_paths == set()
        assert result.stats == {"files_updated": 1, "files_failed": 0, "files_skipped": 0}
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
            patch(f"{MODULE}.os.listdir", return_value=names),
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


@pytest.mark.unit
@pytest.mark.mocked
class TestEnumeratedEntriesAndPerFileClassification:
    """Scanner corroboration inputs and the DD §15 Q5 escalation split (RED)."""

    def test_enumerated_entries_are_raw_listing_names(self, tmp_path: Path) -> None:
        """``enumerated_entries`` carries every raw ``os.listdir`` name — audio,
        non-audio and failed names alike — because corroboration is set membership.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        _make_audio_file(folder_path / "song.mp3")
        _make_audio_file(folder_path / "other.flac")
        (folder_path / "notes.txt").write_bytes(b"notes")
        failing = _make_audio_file(folder_path / "broken.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                side_effect=lambda path, _db: _make_valid_library_path(Path(path)),
            ),
            patch(f"{MODULE}.os.stat", _stat_raising_for(failing, OSError(errno.EACCES, "denied"))),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(1)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.enumerated_entries == {"song.mp3", "other.flac", "broken.mp3", "notes.txt"}
        assert result.stats["files_failed"] == 1
        assert result.warnings
        # The two healthy audio entries are still discovered and upserted.
        assert {Path(entry["path"]).name for entry in result.file_entries} == {"song.mp3", "other.flac"}

    @pytest.mark.parametrize("error_number", [errno.EACCES, errno.ENOTDIR, errno.ELOOP])
    def test_isolated_per_file_stat_failure_is_counted_warned_and_witnessed(
        self, tmp_path: Path, error_number: int
    ) -> None:
        """An isolated per-file stat failure counts ``files_failed``, warns, keeps
        the folder successful, and leaves the failed entry's name witnessed."""
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        failing = _make_audio_file(folder_path / "broken.mp3")

        with patch(f"{MODULE}.os.stat", _stat_raising_for(failing, OSError(error_number, "per-file"))):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.enumerated_entries == {"broken.mp3"}
        assert result.stats["files_failed"] == 1
        assert result.stats["files_updated"] == 0
        assert result.file_entries == []
        assert any("broken.mp3" in warning for warning in result.warnings)

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(OSError(errno.ENOSPC, "full"), id="storage_full"),
            pytest.param(OSError(errno.EROFS, "read-only"), id="read_only_fs"),
            pytest.param(OSError(), id="unknown"),
        ],
    )
    def test_non_escalating_kinds_are_isolated_per_file_failures(self, tmp_path: Path, error: OSError) -> None:
        """The non-mount-level kinds stay isolated per-file failures.

        ``storage_full`` (ENOSPC), ``read_only_fs`` (EROFS) and ``unknown`` (no
        errno) are absent from ``_MOUNT_LEVEL_KINDS``: they increment
        ``files_failed``, append a warning, keep the folder reconciled and leave
        the raw name witnessed. Were any of them promoted to a mount-level kind
        the call would raise instead of returning, failing these assertions.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        failing = _make_audio_file(folder_path / "broken.mp3")

        with patch(f"{MODULE}.os.stat", _stat_raising_for(failing, error)):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.enumerated_entries == {"broken.mp3"}
        assert result.stats["files_failed"] == 1
        assert result.stats["files_updated"] == 0
        assert result.file_entries == []
        assert any("broken.mp3" in warning for warning in result.warnings)

    @pytest.mark.parametrize("error_number", [errno.EIO, errno.ESTALE, errno.ENOENT])
    def test_mount_level_stat_failure_propagates_as_oserror(self, tmp_path: Path, error_number: int) -> None:
        """Every mount/storage-level kind (transient_io, storage_unavailable,
        unconfirmed_missing) re-raises so the caller treats the folder as
        unreconciled (#164 contract), never as an authoritative empty folder."""
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        failing = _make_audio_file(folder_path / "broken.mp3")

        with (
            patch(f"{MODULE}.os.stat", _stat_raising_for(failing, OSError(error_number, "mount gone"))),
            pytest.raises(OSError),
        ):
            scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

    def test_exactly_one_listdir_and_one_stat_per_audio_entry(self, tmp_path: Path) -> None:
        """No added probe: exactly one ``os.listdir`` and one ``os.stat`` per audio
        entry — the metadata stat is reused for classification, never repeated."""
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        _make_audio_file(folder_path / "a.mp3")
        _make_audio_file(folder_path / "b.flac")
        (folder_path / "notes.txt").write_bytes(b"notes")

        real_listdir = os.listdir
        real_stat = os.stat
        counts = {"listdir": 0, "stat": 0}

        def _counting_listdir(path: object) -> list[str]:
            counts["listdir"] += 1
            return real_listdir(path)  # type: ignore[arg-type]

        def _counting_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            counts["stat"] += 1
            return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                side_effect=lambda path, _db: _make_valid_library_path(Path(path)),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(1)),
            patch.object(os, "listdir", _counting_listdir),
            patch.object(os, "stat", _counting_stat),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert counts["listdir"] == 1
        assert counts["stat"] == 2
        assert result.enumerated_entries == {"a.mp3", "b.flac", "notes.txt"}

    def test_non_regular_audio_entry_is_isolated_failure_and_witnessed(self, tmp_path: Path) -> None:
        """A directory whose name looks like audio is a per-file failure.

        It must be counted, warned about with ``not a regular file``, left in
        ``enumerated_entries`` as raw listing material, and excluded from the
        discovered/upserted set so classification cannot silently change.
        """
        mock_db = MagicMock()
        library_root = tmp_path / "music"
        folder_path = library_root / "Rock"
        folder_path.mkdir(parents=True)
        pseudo_track = folder_path / "x.mp3"
        pseudo_track.mkdir()
        real_track = _make_audio_file(folder_path / "song.mp3")

        with (
            patch(
                f"{MODULE}.build_library_path_from_input",
                side_effect=lambda path, _db: _make_valid_library_path(Path(path)),
            ),
            patch(f"{MODULE}.now_ms", return_value=Milliseconds(1)),
        ):
            result = scan_folder_files(
                folder_path=folder_path,
                library_root=library_root,
                existing_files={},
                db=mock_db,
            )

        assert result.stats["files_failed"] == 1
        assert any("not a regular file" in warning for warning in result.warnings)
        assert result.enumerated_entries == {"x.mp3", "song.mp3"}
        assert str(pseudo_track) not in result.discovered_paths
        assert result.discovered_paths == {str(real_track)}
        assert {Path(entry["path"]).name for entry in result.file_entries} == {"song.mp3"}
