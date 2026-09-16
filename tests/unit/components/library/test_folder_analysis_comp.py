"""Tests for folder discovery failure recording.

``discover_library_folders`` must make discovery/measurement failures explicit:
a directory the walk cannot enter (``os.walk`` ``onerror``) or measure
(``OSError``) is recorded as an uninspected library-relative path while
successful discovery is unchanged.
"""

from __future__ import annotations

import errno
import os
from typing import TYPE_CHECKING, Any

import pytest

import nomarr.components.library.folder_analysis_comp as comp
from nomarr.components.library.folder_analysis_comp import FolderDiscovery, discover_library_folders

if TYPE_CHECKING:
    from pathlib import Path


def _make_library(tmp_path: Path) -> Path:
    root = tmp_path / "music"
    root.mkdir()
    return root


@pytest.mark.unit
@pytest.mark.mocked
class TestDiscoverLibraryFoldersUninspected:
    def test_walk_error_is_recorded_as_uninspected_while_folders_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_library(tmp_path)
        for rel in ("ok", "other"):
            folder = root / rel
            folder.mkdir()
            (folder / "a.flac").write_bytes(b"x")

        def fake_walk(top: str, onerror: Any = None, **kwargs: Any) -> Any:
            yield (str(root), ["ok", "other"], [])
            yield (str(root / "ok"), [], ["a.flac"])
            yield (str(root / "other"), [], ["a.flac"])
            assert onerror is not None
            onerror(OSError(13, "Permission denied", str(root / "bad")))

        monkeypatch.setattr(comp.os, "walk", fake_walk)

        result = discover_library_folders(root, [root])

        assert isinstance(result, FolderDiscovery)
        assert {f.rel_path for f in result.folders} == {"ok", "other"}
        assert result.uninspected_rel_paths == {"bad"}

    def test_measurement_oserror_is_recorded_and_folder_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_library(tmp_path)
        bad = root / "bad"
        bad.mkdir()
        (bad / "a.flac").write_bytes(b"x")

        def fake_walk(top: str, onerror: Any = None, **kwargs: Any) -> Any:
            yield (str(root), ["bad"], [])
            yield (str(bad), [], ["a.flac"])

        def fake_mtime(folder_path: str) -> int:
            if folder_path == str(bad):
                raise OSError("cannot stat")
            return 1000

        monkeypatch.setattr(comp.os, "walk", fake_walk)
        monkeypatch.setattr(comp, "_get_folder_mtime", fake_mtime)

        result = discover_library_folders(root, [root])

        assert result.folders == []
        assert result.uninspected_rel_paths == {"bad"}

    def test_enumeration_oserror_is_recorded_when_mtime_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_library(tmp_path)
        bad = root / "bad"
        bad.mkdir()

        def fake_walk(top: str, onerror: Any = None, **kwargs: Any) -> Any:
            yield (str(root), ["bad"], [])
            yield (str(bad), [], ["a.flac"])

        monkeypatch.setattr(comp.os, "walk", fake_walk)
        monkeypatch.setattr(comp, "_get_folder_mtime", lambda _path: 1000)

        def fake_listdir(folder_path: str) -> list[str]:
            if folder_path == str(bad):
                raise OSError("cannot enumerate")
            return []

        monkeypatch.setattr(comp.os, "listdir", fake_listdir)

        result = discover_library_folders(root, [root])

        assert result.folders == []
        assert result.uninspected_rel_paths == {"bad"}

    def test_walk_invoked_with_callable_onerror_that_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_library(tmp_path)
        captured: dict[str, Any] = {}

        def spy_walk(top: str, onerror: Any = None, **kwargs: Any) -> Any:
            captured["onerror"] = onerror
            assert onerror is not None
            onerror(OSError(13, "Permission denied", str(root / "denied")))
            return iter(())

        monkeypatch.setattr(comp.os, "walk", spy_walk)

        result = discover_library_folders(root, [root])

        assert callable(captured["onerror"])
        assert result.uninspected_rel_paths == {"denied"}

    def test_walk_error_outside_root_does_not_raise(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = _make_library(tmp_path)

        def spy_walk(top: str, onerror: Any = None, **kwargs: Any) -> Any:
            assert onerror is not None
            onerror(OSError(13, "Permission denied", str(tmp_path / "elsewhere")))
            return iter(())

        monkeypatch.setattr(comp.os, "walk", spy_walk)

        result = discover_library_folders(root, [root])

        assert result.folders == []
        assert result.uninspected_rel_paths == set()


def _stat_raising_for(target: Any, error: OSError) -> Any:
    """Wrap the real ``os.stat`` so it raises ``error`` for ``target`` only."""
    real_stat = os.stat

    def _stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path) == str(target):
            raise error
        return real_stat(path, *args, **kwargs)

    return _stat


@pytest.mark.unit
@pytest.mark.mocked
class TestEnumeratedEntriesAndMeasurement:
    """Discovery records raw listings and surfaces per-file measurement failures (RED)."""

    def test_enumerated_entries_records_raw_names_for_every_walked_directory(self, tmp_path: Path) -> None:
        root = _make_library(tmp_path)
        (root / "a.mp3").write_bytes(b"x")
        (root / "notes.txt").write_bytes(b"x")
        sub = root / "sub"
        sub.mkdir()
        (sub / "b.flac").write_bytes(b"x")
        (sub / "cover.jpg").write_bytes(b"x")
        empty = root / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_bytes(b"x")

        result = discover_library_folders(root, [root])

        assert result.enumerated_entries[""] == {"a.mp3", "notes.txt", "sub", "empty"}
        assert result.enumerated_entries["sub"] == {"b.flac", "cover.jpg"}
        assert result.enumerated_entries["empty"] == {"readme.txt"}

    def test_folder_whose_audio_entries_all_fail_is_still_emitted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A folder measured zero *solely* because per-file stat calls failed must
        still be emitted (file_count == 0, failed_count > 0) so it can never be
        classified vanished."""
        root = _make_library(tmp_path)
        folder = root / "failed"
        folder.mkdir()
        audio = folder / "a.flac"
        audio.write_bytes(b"x")

        monkeypatch.setattr(comp.os, "stat", _stat_raising_for(audio, OSError(errno.EACCES, "denied")))

        result = discover_library_folders(root, [root])

        emitted = {f.rel_path: f for f in result.folders}
        assert "failed" in emitted
        assert emitted["failed"].file_count == 0
        assert emitted["failed"].failed_count > 0
        assert result.uninspected_rel_paths == set()

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(OSError(errno.ENOSPC, "full"), id="storage_full"),
            pytest.param(OSError(errno.EROFS, "read-only"), id="read_only_fs"),
            pytest.param(OSError(), id="unknown"),
        ],
    )
    def test_non_escalating_per_entry_kinds_emit_folder_rather_than_uninspected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
    ) -> None:
        """The non-mount-level per-entry kinds stay isolated, never uninspected.

        ``storage_full`` (ENOSPC), ``read_only_fs`` (EROFS) and ``unknown`` (no
        errno) are absent from ``_MOUNT_LEVEL_KINDS``: the folder is emitted with
        ``file_count == 0`` and ``failed_count > 0`` and is NOT recorded in
        ``uninspected_rel_paths``. Were any promoted to a mount-level kind the
        folder would be excluded and recorded uninspected, failing this test.
        """
        root = _make_library(tmp_path)
        folder = root / "failed"
        folder.mkdir()
        audio = folder / "a.flac"
        audio.write_bytes(b"x")

        monkeypatch.setattr(comp.os, "stat", _stat_raising_for(audio, error))

        result = discover_library_folders(root, [root])

        emitted = {f.rel_path: f for f in result.folders}
        assert "failed" in emitted
        assert emitted["failed"].file_count == 0
        assert emitted["failed"].failed_count > 0
        assert result.uninspected_rel_paths == set()

    @pytest.mark.parametrize("error_number", [errno.EIO, errno.ESTALE, errno.ENOENT])
    def test_mount_level_per_file_failure_marks_folder_uninspected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
    ) -> None:
        """Every mount/storage-level kind (transient_io, storage_unavailable,
        unconfirmed_missing) propagates so the folder is recorded in
        ``uninspected_rel_paths`` and excluded from ``folders``."""
        root = _make_library(tmp_path)
        folder = root / "storage"
        folder.mkdir()
        audio = folder / "a.flac"
        audio.write_bytes(b"x")

        monkeypatch.setattr(comp.os, "stat", _stat_raising_for(audio, OSError(error_number, "mount gone")))

        result = discover_library_folders(root, [root])

        assert "storage" not in {f.rel_path for f in result.folders}
        assert "storage" in result.uninspected_rel_paths

    def test_non_regular_audio_entry_emits_folder_rather_than_dropping(self, tmp_path: Path) -> None:
        """A folder whose only audio-named entry is a non-regular file must be
        emitted (``file_count == 0``, ``failed_count > 0``) rather than dropped, so
        it can never be classified vanished; the raw name is still enumerated."""
        root = _make_library(tmp_path)
        album = root / "album"
        album.mkdir()
        (album / "x.mp3").mkdir()

        result = discover_library_folders(root, [root])

        emitted = {f.rel_path: f for f in result.folders}
        assert "album" in emitted
        assert emitted["album"].file_count == 0
        assert emitted["album"].failed_count >= 1
        assert "album" not in result.uninspected_rel_paths
        assert result.enumerated_entries["album"] == {"x.mp3"}
