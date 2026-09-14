"""Tests for folder discovery failure recording.

``discover_library_folders`` must make discovery/measurement failures explicit:
a directory the walk cannot enter (``os.walk`` ``onerror``) or measure
(``OSError``) is recorded as an uninspected library-relative path while
successful discovery is unchanged.
"""

from __future__ import annotations

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
