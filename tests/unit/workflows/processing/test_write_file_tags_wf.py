"""Unit tests for ``write_file_tags_wf`` — filtering, resolution, and the workflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.safe_write_comp import SafeWriteResult
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.helpers.dto.path_dto import LibraryPath
from nomarr.workflows.processing.write_file_tags_wf import (
    _filter_tags_for_mode,
    _release_failed_write,
    _resolve_library_path,
    write_file_tags_workflow,
)

_MODULE = "nomarr.workflows.processing.write_file_tags_wf"


@pytest.mark.unit
class TestFilterTagsForMode:
    """Tests for ``_filter_tags_for_mode`` mode filtering logic."""

    @staticmethod
    def _make_tags(*keys: str) -> Tags:
        """Build a Tags DTO from tag key strings."""
        return Tags(items=tuple(Tag(name=k, values=("v",)) for k in keys))

    def test_none_mode_returns_none(self) -> None:
        """target_mode='none' always returns None (clear the namespace)."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "none", has_calibration=True)
        assert result is None

    def test_full_mode_with_calibration_returns_all_tags(self) -> None:
        """target_mode='full' + has_calibration returns all tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "full", has_calibration=True)
        assert len(result.items) == 3
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict", "genre", "tempo"}

    def test_full_mode_without_calibration_filters_mood_tags(self) -> None:
        """target_mode='full' + no calibration filters out mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "genre", "tempo", "mood-loose")
        result = _filter_tags_for_mode(tags, "full", has_calibration=False)
        assert len(result.items) == 2
        keys = {t.name for t in result.items}
        assert keys == {"genre", "tempo"}

    def test_minimal_mode_with_calibration_returns_only_mood_tags(self) -> None:
        """target_mode='minimal' + has_calibration returns only mood-prefixed tags."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre", "tempo")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        assert len(result.items) == 2
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict", "mood-regular"}

    def test_minimal_mode_without_calibration_returns_none(self) -> None:
        """target_mode='minimal' + no calibration: mood tags filtered, then mood filter finds nothing -> None."""
        tags = self._make_tags("mood-strict", "mood-regular", "genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=False)
        assert result is None

    def test_minimal_mode_ignores_non_mood_tags_even_with_calibration(self) -> None:
        """Only mood-prefixed tags pass minimal mode, regardless of calibration."""
        tags = self._make_tags("mood-strict", "nom-valence", "effnet_genre")
        result = _filter_tags_for_mode(tags, "minimal", has_calibration=True)
        keys = {t.name for t in result.items}
        assert keys == {"mood-strict"}

    def test_none_input_tags_returns_none(self) -> None:
        """None input Tags yield None (clear) in all modes."""
        tags: Tags | None = None
        for mode in ("none", "minimal", "full"):
            for calib in (True, False):
                result = _filter_tags_for_mode(tags, mode, has_calibration=calib)
                assert result is None


@pytest.mark.unit
class TestFailedWriteCleanup:
    """Failed writes release claims without clearing pending state."""

    def test_release_failed_write_only_releases_claim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed write remains eligible for reconciliation retry."""
        calls: list[tuple[object, SongIdentity, str]] = []

        def record_release(db: object, file_key: SongIdentity, worker_id: str) -> None:
            calls.append((db, file_key, worker_id))

        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.release_claim",
            record_release,
        )

        db = object()
        identity = SongIdentity(
            library=LibraryIdentity(library_uuid="uuid-lib1"),
            normalized_path="song.mp3",
        )
        _release_failed_write(db, identity, "reconcile:1")

        assert calls == [(db, identity, "reconcile:1")]


def _identity(normalized_path: str = "song.mp3") -> SongIdentity:
    """Build the semantic locator shared by the workflow fixtures."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="uuid-lib1", name="lib1", root_path="/music"),
        normalized_path=normalized_path,
    )


def _song(
    *,
    path: str = "/music/song.mp3",
    normalized_path: str = "song.mp3",
    modified_time: int = 1000,
) -> Song:
    """Build a semantic ``Song`` for path-resolution and workflow tests."""
    return Song(
        path=path,
        normalized_path=normalized_path,
        file_size=100,
        modified_time=modified_time,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _library() -> Library:
    """Build the domain ``Library`` owning ``/music``."""
    return Library(name="lib1", root_path="/music", library_uuid="uuid-lib1")


def _library_path() -> LibraryPath:
    """Build a validated ``LibraryPath`` for ``song.mp3``."""
    return LibraryPath(
        relative="song.mp3",
        absolute=Path("/music/song.mp3"),
        library_id="lib1",
        status="valid",
    )


@pytest.fixture
def workflow(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Wire the workflow module with typed recorders and a fake ``TagWriter``."""
    db = MagicMock()
    release_calls: list[tuple[object, SongIdentity, str]] = []
    written_calls: list[tuple[object, SongIdentity, str]] = []

    def record_release(database: object, file_key: SongIdentity, worker_id: str) -> None:
        release_calls.append((database, file_key, worker_id))

    def record_set_written(database: object, file_key: SongIdentity, worker_id: str) -> None:
        written_calls.append((database, file_key, worker_id))

    monkeypatch.setattr(f"{_MODULE}.release_claim", record_release)
    monkeypatch.setattr(f"{_MODULE}.set_file_written", record_set_written)
    monkeypatch.setattr(f"{_MODULE}.find_library_containing_path", lambda _db, _path: _library())
    monkeypatch.setattr(f"{_MODULE}.build_library_path_from_db", lambda **_kwargs: _library_path())
    monkeypatch.setattr(f"{_MODULE}.resolve_library_root", lambda _db, _lib: Path("/music"))

    writer_cls = MagicMock()
    writer_cls.return_value.write_safe.return_value = SafeWriteResult(success=True, new_mtime_ms=4242)
    monkeypatch.setattr(f"{_MODULE}.TagWriter", writer_cls)

    db.library.list_tags_for_song.return_value = ()
    return SimpleNamespace(
        db=db,
        identity=_identity(),
        release_calls=release_calls,
        written_calls=written_calls,
        writer_cls=writer_cls,
    )


@pytest.mark.unit
class TestResolveLibraryPath:
    """Direct coverage for ``_resolve_library_path`` library/path resolution."""

    def test_empty_stored_path_returns_none_none(self) -> None:
        """A song carrying no physical path cannot resolve a library."""
        assert _resolve_library_path(_song(path=""), MagicMock()) == (None, None)

    def test_unknown_library_returns_none_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No containing library is a clean ``(None, None)`` miss."""
        monkeypatch.setattr(f"{_MODULE}.find_library_containing_path", lambda _db, _path: None)
        assert _resolve_library_path(_song(), MagicMock()) == (None, None)

    def test_invalid_library_path_returns_none_and_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A known library with an invalid path returns the library for diagnosis."""
        library = _library()
        invalid = LibraryPath(
            relative="song.mp3",
            absolute=Path("/music/song.mp3"),
            library_id="lib1",
            status="not_found",
            reason="gone",
        )
        monkeypatch.setattr(f"{_MODULE}.find_library_containing_path", lambda _db, _path: library)
        monkeypatch.setattr(f"{_MODULE}.build_library_path_from_db", lambda **_kwargs: invalid)
        assert _resolve_library_path(_song(), MagicMock()) == (None, library)

    def test_valid_path_returns_path_and_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A valid path returns the ``LibraryPath`` and its library, keyed by name."""
        library = _library()
        path = _library_path()
        captured: dict[str, object] = {}

        def fake_build(**kwargs: object) -> LibraryPath:
            captured.update(kwargs)
            return path

        monkeypatch.setattr(f"{_MODULE}.find_library_containing_path", lambda _db, _path: library)
        monkeypatch.setattr(f"{_MODULE}.build_library_path_from_db", fake_build)
        assert _resolve_library_path(_song(), MagicMock()) == (path, library)
        assert captured["library_id"] == library.name
        assert captured["check_disk"] is True


@pytest.mark.unit
class TestWriteFileTagsWorkflow:
    """Direct coverage for the migrated ``write_file_tags_workflow``."""

    @staticmethod
    def _run(workflow: SimpleNamespace, *, mode: str = "full", calibration: bool = True):
        return write_file_tags_workflow(
            workflow.db,
            workflow.identity,
            worker_id="reconcile:lib1",
            target_mode=mode,
            has_calibration=calibration,
        )

    def test_missing_locator_releases_claim_and_reports_file_not_found(self, workflow: SimpleNamespace) -> None:
        """A stale/missing locator is a clean miss that releases the exact claim."""
        workflow.db.library.get_song.return_value = None
        result = self._run(workflow)
        assert result.file_key is workflow.identity
        assert result.success is False
        assert result.error == "File not found"
        assert workflow.identity.normalized_path not in (result.error or "")
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]
        assert workflow.written_calls == []

    def test_invalid_path_releases_claim(self, workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unresolvable path releases the claim and returns the generic failure."""
        workflow.db.library.get_song.return_value = _song()
        monkeypatch.setattr(f"{_MODULE}.find_library_containing_path", lambda _db, _path: None)
        result = self._run(workflow)
        assert result.error == "Invalid path"
        assert result.file_key is workflow.identity
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]

    def test_missing_library_root_releases_claim(
        self, workflow: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A known library whose root does not resolve fails without writing."""
        workflow.db.library.get_song.return_value = _song()
        monkeypatch.setattr(f"{_MODULE}.resolve_library_root", lambda _db, _lib: None)
        result = self._run(workflow)
        assert result.error == "Library not found"
        assert result.file_key is workflow.identity
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]

    def test_list_tags_projects_only_nom_namespace(self, workflow: SimpleNamespace) -> None:
        """Only ``nom`` assignments cross into the writer's ``Tags`` DTO."""
        workflow.db.library.get_song.return_value = _song(modified_time=555)
        workflow.db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="rock", namespace="nom"),
            SongTagAssignment(name="other", value="hidden", namespace="default"),
            SongTagAssignment(name="mood-strict", value="happy", namespace="nom"),
        )
        result = self._run(workflow, mode="full", calibration=True)
        workflow.writer_cls.assert_called_once_with(overwrite=True, namespace="nom")
        args = workflow.writer_cls.return_value.write_safe.call_args.args
        assert args[3] == 555
        tags = args[1]
        assert isinstance(tags, Tags)
        assert {tag.name: tag.values for tag in tags.items} == {"genre": ("rock",), "mood-strict": ("happy",)}
        assert result.tags_written == 2

    def test_success_sets_modified_time_and_file_written_with_identity(self, workflow: SimpleNamespace) -> None:
        """A successful write syncs mtime and advances state with the ``SongIdentity``."""
        workflow.db.library.get_song.return_value = _song()
        workflow.writer_cls.return_value.write_safe.return_value = SafeWriteResult(success=True, new_mtime_ms=4242)
        workflow.db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="rock", namespace="nom"),
        )
        result = self._run(workflow)
        assert result.success is True
        assert result.file_key is workflow.identity
        assert result.tags_written == 1
        workflow.db.library.set_modified_time.assert_called_once_with(workflow.identity, 4242)
        assert workflow.written_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]
        assert workflow.release_calls == []

    def test_success_without_new_mtime_skips_modified_time(self, workflow: SimpleNamespace) -> None:
        """A writer that reports no new mtime does not touch the scalar intent."""
        workflow.db.library.get_song.return_value = _song()
        workflow.writer_cls.return_value.write_safe.return_value = SafeWriteResult(success=True, new_mtime_ms=None)
        result = self._run(workflow)
        assert result.success is True
        workflow.db.library.set_modified_time.assert_not_called()
        assert workflow.written_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]

    def test_safe_write_failure_releases_claim_and_maps_error(self, workflow: SimpleNamespace) -> None:
        """A generic safe-write failure releases the claim and maps the error."""
        workflow.db.library.get_song.return_value = _song()
        workflow.writer_cls.return_value.write_safe.return_value = SafeWriteResult(success=False, error="boom")
        result = self._run(workflow)
        assert result.success is False
        assert result.error == "Safe write failed: boom"
        assert result.file_key is workflow.identity
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]
        assert workflow.written_calls == []

    def test_file_modified_externally_preserves_error_token(self, workflow: SimpleNamespace) -> None:
        """External modification keeps its retry token and releases the claim."""
        workflow.db.library.get_song.return_value = _song()
        workflow.writer_cls.return_value.write_safe.return_value = SafeWriteResult(
            success=False,
            error="file_modified_externally",
        )
        result = self._run(workflow)
        assert result.error == "file_modified_externally"
        assert result.file_key is workflow.identity
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]

    def test_unexpected_exception_is_redacted(self, workflow: SimpleNamespace) -> None:
        """An unexpected failure stays generic and leaks no path or locator detail."""
        workflow.db.library.get_song.side_effect = RuntimeError("secret internal /music/song.mp3")
        result = self._run(workflow)
        error = result.error or ""
        assert result.success is False
        assert error == "Unexpected error during tag write"
        assert "secret" not in error
        assert "/music" not in error
        assert result.file_key is workflow.identity
        assert workflow.release_calls == [(workflow.db, workflow.identity, "reconcile:lib1")]
