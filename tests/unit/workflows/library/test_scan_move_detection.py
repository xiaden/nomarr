"""Behavioral regressions for move detection in the library scan workflows.

Both ``scan_library_quick_workflow`` and ``scan_library_full_workflow`` must
reconcile detected relocations *before* treating a missing path as a delete and a
newly discovered path as an insert. These tests drive the real
``detect_file_moves`` / ``apply_detected_moves`` / ``detect_file_move_via_db``
component (only chromaprint decoding is stubbed) through the workflow so the
wiring itself is exercised:

* moves within one changed folder,
* moves across two changed folders,
* moves from a folder that vanished entirely into a discovered location,
* the DB-lookup fallback for otherwise-unmatched new files, and its rejection
  when the matched source is still present on disk,
* multi-move / multi-new batches reconciled per file,
* quick-scan skipping of unchanged cached folders,
* the no-chromaprint cost gate (no audio decode without a print-bearing
  candidate),
* negatives: a genuinely new file is still inserted, and a genuinely missing
  file is still removed.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

import nomarr.workflows.library.scan_library_full_wf as full_wf
import nomarr.workflows.library.scan_library_quick_wf as quick_wf
from nomarr.components.library.file_batch_scanner_comp import FileBatchResult
from nomarr.components.library.song_query_types import StateTaggedSong
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_HYDRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_HYDRATED,
    STATE_NOT_SCANNED,
    STATE_SCANNED,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate

if TYPE_CHECKING:
    from collections.abc import Iterator

_MOVEMENT_MODULE = "nomarr.components.library.move_detection_comp"

_LIBRARY = Library(library_uuid="45064f6d-d92e-5179-ad4d-6a15c1354737", name="Main Library", root_path="/music")
_LIBRARY_IDENTITY = LibraryIdentity(
    library_uuid="45064f6d-d92e-5179-ad4d-6a15c1354737", name="Main Library", root_path="/music"
)


def _song(path: str, normalized_path: str, chromaprint: str | None, duration: float | None = 180.0) -> Song:
    return Song(
        path=path,
        normalized_path=normalized_path,
        file_size=1000,
        modified_time=2000,
        duration_seconds=duration,
        chromaprint=chromaprint,
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=0,
    )


def _carrier(song: Song) -> StateTaggedSong:
    return StateTaggedSong(
        candidate=SongStateCandidate(
            identity=SongIdentity(library=_LIBRARY_IDENTITY, normalized_path=song.normalized_path),
            song=song,
            states=(),
        ),
        has_tagged_state=True,
    )


def _entry(path: str, normalized_path: str) -> dict[str, Any]:
    return {
        "path": path,
        "normalized_path": normalized_path,
        "file_size": 2048,
        "modified_time": 9999,
        "scanned_at": 1,
    }


def _batch(
    *,
    entries: list[dict[str, Any]] | None = None,
    discovered: set[str] | None = None,
) -> FileBatchResult:
    entries = entries or []
    return FileBatchResult(
        file_entries=entries,
        discovered_paths=discovered or set(),
        new_file_paths={e["path"] for e in entries},
        stats={"files_updated": 0, "files_failed": 0, "files_skipped": 0},
        warnings=[],
        edge_bootstraps=[],
    )


def _fake_library_path(path: str, db: Any) -> Any:
    return SimpleNamespace(is_valid=lambda: True, absolute=path)


@contextmanager
def _patched_scan(
    module: Any,
    *,
    folders: list[SimpleNamespace],
    existing: dict[str, dict[str, StateTaggedSong]],
    batches: dict[str, FileBatchResult],
    db_folder_paths: set[str] | None = None,
    chromaprint_by_path: dict[str, str] | None = None,
    db_candidate: Song | None = None,
    cached_folders: dict[str, SimpleNamespace] | None = None,
    folder_errors: dict[str, Exception] | None = None,
    folder_transient_errors: dict[str, Exception] | None = None,
) -> Iterator[SimpleNamespace]:
    """Patch one scan workflow module and the move-detection chromaprint edges.

    ``existing`` maps a folder rel path to its DB carrier map; ``batches`` maps a
    folder absolute path to the ``FileBatchResult`` the scan returns. Only the
    expensive chromaprint decode is stubbed; move matching/application runs for
    real against a mocked ``Database``. ``cached_folders`` seeds the quick-scan
    folder cache so unchanged folders can be skipped. ``folder_errors`` maps a
    folder absolute path to an exception raised on every walk attempt, simulating
    a folder whose walk fails after the retry. ``folder_transient_errors`` maps a
    folder absolute path to an exception raised only on the first walk attempt,
    simulating a transient failure that the retry recovers from.
    """
    db = MagicMock()
    db.library = MagicMock()
    db.library.count_songs_for_library.return_value = 0

    def _destination(command: Any) -> SongIdentity:
        return SongIdentity(library=command.song_identity.library, normalized_path=command.scan.normalized_path)

    db.library.move_library_song.side_effect = _destination

    chromaprints = chromaprint_by_path or {}
    errors = folder_errors or {}
    transient_errors = folder_transient_errors or {}
    transient_attempts: dict[str, int] = {}

    def _compute(library_path: Any) -> str:
        return chromaprints[library_path.absolute]

    def _scan_folder(**kw: Any) -> FileBatchResult:
        folder_path = str(kw["folder_path"])
        if folder_path in errors:
            raise errors[folder_path]
        if folder_path in transient_errors:
            attempt = transient_attempts.get(folder_path, 0)
            transient_attempts[folder_path] = attempt + 1
            if attempt == 0:
                raise transient_errors[folder_path]
        return batches[folder_path]

    mocks = SimpleNamespace()
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "resolve_library_for_scan", return_value=_LIBRARY))
        stack.enter_context(patch.object(module, "validate_library_root"))
        stack.enter_context(patch.object(module, "get_folder_rel_paths", return_value=db_folder_paths or set()))
        stack.enter_context(patch.object(module, "get_cached_folders", return_value=cached_folders or {}))
        stack.enter_context(patch.object(module, "discover_library_folders", return_value=folders))
        mocks.get_songs_for_folder = stack.enter_context(
            patch.object(module, "get_songs_for_folder", side_effect=lambda _db, _lib, rel: existing.get(rel, {}))
        )
        mocks.scan_folder_files = stack.enter_context(
            patch.object(module, "scan_folder_files", side_effect=_scan_folder)
        )
        upsert_returns: list[tuple[list[dict[str, Any]], list[MagicMock]]] = []

        def _upsert(_db: Any, _lib: Any, entries: list[dict[str, Any]], *_a: Any) -> list[MagicMock]:
            identities = [MagicMock() for _ in entries]
            upsert_returns.append((list(entries), identities))
            return identities

        mocks.upsert = stack.enter_context(patch.object(module, "upsert_scanned_files", side_effect=_upsert))
        mocks.upsert_returns = upsert_returns
        mocks.transition_song_state = stack.enter_context(patch.object(module, "transition_song_state"))
        mocks.remove_deleted = stack.enter_context(
            patch.object(module, "remove_deleted_files", side_effect=lambda _db, _lib, paths: len(paths))
        )
        stack.enter_context(patch.object(module, "save_folder_record"))
        stack.enter_context(patch.object(module, "cleanup_stale_folders"))
        stack.enter_context(patch.object(module, "cleanup_orphaned_entities_workflow"))
        stack.enter_context(patch.object(module, "update_scan_progress"))
        stack.enter_context(patch.object(module, "mark_scan_completed"))

        stack.enter_context(patch(f"{_MOVEMENT_MODULE}.build_library_path_from_input", side_effect=_fake_library_path))
        mocks.compute_chromaprint = stack.enter_context(
            patch(f"{_MOVEMENT_MODULE}.compute_chromaprint_for_file", side_effect=_compute)
        )
        stack.enter_context(patch(f"{_MOVEMENT_MODULE}.find_move_candidate_by_chromaprint", return_value=db_candidate))

        yield SimpleNamespace(db=db, mocks=mocks)


@pytest.fixture(params=["quick", "full"])
def workflow(request: pytest.FixtureRequest) -> tuple[Any, Any]:
    """Return ``(module, callable)`` for each scan workflow implementation."""
    if request.param == "quick":
        return quick_wf, quick_wf.scan_library_quick_workflow
    return full_wf, full_wf.scan_library_full_workflow


def _folder(rel_path: str, file_count: int = 1) -> SimpleNamespace:
    return SimpleNamespace(rel_path=rel_path, abs_path=f"/music/{rel_path}", mtime=100, file_count=file_count)


def _upsert_paths(mock: MagicMock) -> set[str]:
    paths: set[str] = set()
    for call in mock.call_args_list:
        for entry in call.args[2]:
            paths.add(entry["path"])
    return paths


def _removed_paths(mock: MagicMock) -> set[str]:
    paths: set[str] = set()
    for call in mock.call_args_list:
        paths.update(call.args[2])
    return paths


def _scanned_paths(mock: MagicMock) -> set[str]:
    return {str(call.kwargs["folder_path"]) for call in mock.call_args_list}


def _cached_folder(rel_path: str, *, mtime: int = 100, file_count: int = 1) -> SimpleNamespace:
    """A cached folder record matching :func:`_folder` when mtime/count are unchanged."""
    return SimpleNamespace(rel_path=rel_path, abs_path=f"/music/{rel_path}", mtime=mtime, file_count=file_count)


@pytest.mark.unit
@pytest.mark.mocked
class TestScanMoveDetection:
    def _run(self, module: Any, callable_: Any, db: MagicMock, **kwargs: Any) -> dict[str, Any]:
        assert module in (quick_wf, full_wf)
        return cast("dict[str, Any]", callable_(db, _LIBRARY, tagger_version="v1"))

    def test_move_within_changed_folder_is_applied_not_deleted_and_added(self, workflow: tuple[Any, Any]) -> None:
        module, callable_ = workflow
        old = _song("/music/old/a.flac", "old/a.flac", "cp-a")
        new = _entry("/music/new/a.flac", "new/a.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            chromaprint_by_path={new["path"]: "cp-a"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "old/a.flac"
        assert command.new_path == "/music/new/a.flac"
        assert new["path"] not in _upsert_paths(ctx.mocks.upsert)
        assert old.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 1
        assert result["files_added"] == 0
        assert result["files_removed"] == 0

    def test_move_across_two_changed_folders_is_applied(self, workflow: tuple[Any, Any]) -> None:
        module, callable_ = workflow
        old = _song("/music/a/old.flac", "a/old.flac", "cp-shared")
        new = _entry("/music/b/new.flac", "b/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("a"), _folder("b")],
            existing={"a": {old.path: _carrier(old)}, "b": {}},
            batches={
                "/music/a": _batch(discovered=set()),
                "/music/b": _batch(entries=[new], discovered={new["path"]}),
            },
            chromaprint_by_path={new["path"]: "cp-shared"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "a/old.flac"
        assert command.new_path == "/music/b/new.flac"
        assert new["path"] not in _upsert_paths(ctx.mocks.upsert)
        assert old.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 1

    def test_move_from_vanished_folder_into_discovered_location_is_applied(self, workflow: tuple[Any, Any]) -> None:
        module, callable_ = workflow
        old = _song("/music/gone/old.flac", "gone/old.flac", "cp-vanished")
        new = _entry("/music/fresh/new.flac", "fresh/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("fresh")],
            existing={"gone": {old.path: _carrier(old)}, "fresh": {}},
            batches={"/music/fresh": _batch(entries=[new], discovered={new["path"]})},
            db_folder_paths={"gone"},
            chromaprint_by_path={new["path"]: "cp-vanished"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "gone/old.flac"
        assert command.new_path == "/music/fresh/new.flac"
        assert new["path"] not in _upsert_paths(ctx.mocks.upsert)
        assert old.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 1

    def test_db_fallback_detects_move_for_unmatched_new_file(self, workflow: tuple[Any, Any]) -> None:
        """A new file whose in-memory missing candidate does not match is looked
        up directly in the DB and moved instead of inserted, when the DB match's
        source is genuinely absent from disk."""
        module, callable_ = workflow
        old = _song("/music/f1/old.flac", "f1/old.flac", "cp-unrelated")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        # The DB candidate lives in a folder that has vanished entirely, so its
        # path is genuinely absent from disk and the relocation is legitimate.
        vanished = _song("/music/gone/z.flac", "gone/z.flac", "cp-move")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            db_folder_paths={"gone"},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidate=vanished,
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "gone/z.flac"
        assert command.new_path == "/music/f1/new.flac"
        assert new["path"] not in _upsert_paths(ctx.mocks.upsert)
        # The unrelated missing file is truly missing and is still removed.
        assert old.path in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 1
        assert result["files_removed"] == 1

    def test_db_fallback_rejects_match_to_still_present_source(self, workflow: tuple[Any, Any]) -> None:
        """A DB chromaprint match whose source is still present on disk must not
        be relocated: the live row keeps its path and the new file is inserted."""
        module, callable_ = workflow
        # A chromaprint-bearing missing candidate forces the move pass to run,
        # but does not match the new file.
        trigger = _song("/music/f1/trigger.flac", "f1/trigger.flac", "cp-trigger")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        # The DB candidate is a live song: its path is discovered this scan.
        live = _song("/music/f1/live.flac", "f1/live.flac", "cp-move")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {trigger.path: _carrier(trigger)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"], live.path})},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidate=live,
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert live.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1
        assert result["files_removed"] == 1

    def test_quick_scan_skips_unchanged_cached_folder_and_detects_move_in_changed_folder(self) -> None:
        """An unchanged cached folder is not walked or reconciled, while a move in
        a changed folder is still detected and applied."""
        stale = _song("/music/cached/stale.flac", "cached/stale.flac", "cp-stale")
        old = _song("/music/f1/old.flac", "f1/old.flac", "cp-a")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            quick_wf,
            folders=[_folder("cached"), _folder("f1")],
            existing={"cached": {stale.path: _carrier(stale)}, "f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            cached_folders={"cached": _cached_folder("cached")},
            chromaprint_by_path={new["path"]: "cp-a"},
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        assert _scanned_paths(ctx.mocks.scan_folder_files) == {"/music/f1"}
        walked_folders = {call.args[2] for call in ctx.mocks.get_songs_for_folder.call_args_list}
        assert "cached" not in walked_folders
        assert stale.path not in _removed_paths(ctx.mocks.remove_deleted)
        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "f1/old.flac"
        assert result["files_moved"] == 1
        assert result["folders_skipped"] == 1

    def test_no_chromaprint_candidate_avoids_audio_decode(self, workflow: tuple[Any, Any]) -> None:
        """With only chromaprint-less missing candidates the move pass is skipped,
        so no audio is decoded, yet the missing file is still reconciled."""
        module, callable_ = workflow
        old = _song("/music/f1/old.flac", "f1/old.flac", None)
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.mocks.compute_chromaprint.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert old.path in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1
        assert result["files_removed"] == 1

    def test_multi_move_and_new_batch_is_reconciled_per_file(self, workflow: tuple[Any, Any]) -> None:
        """A batch with two moves, one genuinely-new file, and one unmatched missing
        file reconciles each independently: moves applied, new inserted, missing removed."""
        module, callable_ = workflow
        old_a = _song("/music/f1/a-old.flac", "f1/a-old.flac", "cp-a")
        old_b = _song("/music/f1/b-old.flac", "f1/b-old.flac", "cp-b")
        gone = _song("/music/f1/gone.flac", "f1/gone.flac", None)
        new_a = _entry("/music/f1/a-new.flac", "f1/a-new.flac")
        new_b = _entry("/music/f1/b-new.flac", "f1/b-new.flac")
        brand_new = _entry("/music/f1/brand-new.flac", "f1/brand-new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={
                "f1": {old_a.path: _carrier(old_a), old_b.path: _carrier(old_b), gone.path: _carrier(gone)},
            },
            batches={
                "/music/f1": _batch(
                    entries=[new_a, new_b, brand_new],
                    discovered={new_a["path"], new_b["path"], brand_new["path"]},
                ),
            },
            chromaprint_by_path={new_a["path"]: "cp-a", new_b["path"]: "cp-b", brand_new["path"]: "cp-unmatched"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        moved_sources = {
            call.args[0].song_identity.normalized_path for call in ctx.db.library.move_library_song.call_args_list
        }
        assert moved_sources == {"f1/a-old.flac", "f1/b-old.flac"}
        upserted = _upsert_paths(ctx.mocks.upsert)
        assert brand_new["path"] in upserted
        assert new_a["path"] not in upserted
        assert new_b["path"] not in upserted
        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert removed == {gone.path}
        assert result["files_moved"] == 2
        assert result["files_added"] == 1
        assert result["files_removed"] == 1

    def test_genuinely_new_file_is_inserted(self, workflow: tuple[Any, Any]) -> None:
        module, callable_ = workflow
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            chromaprint_by_path={new["path"]: "cp-new"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        ctx.db.library.move_library_song.assert_not_called()
        ctx.mocks.remove_deleted.assert_not_called()
        assert result["files_added"] == 1
        assert result["files_moved"] == 0
        assert result["files_removed"] == 0

    def test_genuinely_missing_file_is_removed(self, workflow: tuple[Any, Any]) -> None:
        module, callable_ = workflow
        old = _song("/music/f1/old.flac", "f1/old.flac", "cp-gone")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(discovered=set())},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        assert old.path in _removed_paths(ctx.mocks.remove_deleted)
        ctx.mocks.upsert.assert_not_called()
        ctx.db.library.move_library_song.assert_not_called()
        assert result["files_removed"] == 1
        assert result["files_moved"] == 0

    def test_modified_entry_is_upserted_immediately_and_new_entry_deferred(self, workflow: tuple[Any, Any]) -> None:
        """A file entry whose physical path is already a DB key for the folder is
        \"modified\": it is upserted immediately and its hydration is reset, while a
        genuinely new sibling is deferred to the later move-detection/insert step."""
        module, callable_ = workflow
        modified = _song("/music/f1/mod.flac", "f1/mod.flac", "cp-mod")
        modified_entry = _entry("/music/f1/mod.flac", "f1/mod.flac")
        new_entry = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {modified.path: _carrier(modified)}},
            batches={
                "/music/f1": _batch(
                    entries=[modified_entry, new_entry],
                    discovered={modified_entry["path"], new_entry["path"]},
                )
            },
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        # Two upsert calls: the modified entry immediately, the new entry deferred.
        assert len(ctx.mocks.upsert_returns) == 2
        immediate_entries, modified_identities = ctx.mocks.upsert_returns[0]
        deferred_entries, _ = ctx.mocks.upsert_returns[1]
        assert [e["path"] for e in immediate_entries] == [modified_entry["path"]]
        assert [e["path"] for e in deferred_entries] == [new_entry["path"]]
        # The modified path never reaches the deferred Step-8 insert.
        assert modified_entry["path"] not in {e["path"] for e in deferred_entries}

        # Only the genuinely-new entry is counted as added.
        assert result["files_added"] == 1

        transition_pairs = [call.args[2:4] for call in ctx.mocks.transition_song_state.call_args_list]
        assert transition_pairs.count((STATE_NOT_SCANNED, STATE_SCANNED)) == 2
        assert transition_pairs.count((STATE_ERRORED, STATE_NOT_ERRORED)) == 2
        # The hydration reset targets the modified identities (immediate upsert),
        # never the deferred new entry.
        hydration_call = next(
            call
            for call in ctx.mocks.transition_song_state.call_args_list
            if call.args[2:4] == (STATE_HYDRATED, STATE_NOT_HYDRATED)
        )
        assert hydration_call.args[1] == modified_identities

    def test_modified_only_batch_adds_no_new_files(self, workflow: tuple[Any, Any]) -> None:
        """A batch whose only entry is an already-known path is a pure modification:
        it is upserted and hydration-reset in place, nothing is inserted, and the
        deferred insert is never reached."""
        module, callable_ = workflow
        modified = _song("/music/f1/mod.flac", "f1/mod.flac", "cp-mod")
        modified_entry = _entry("/music/f1/mod.flac", "f1/mod.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {modified.path: _carrier(modified)}},
            batches={
                "/music/f1": _batch(
                    entries=[modified_entry],
                    discovered={modified_entry["path"]},
                )
            },
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        assert len(ctx.mocks.upsert_returns) == 1
        immediate_entries, _ = ctx.mocks.upsert_returns[0]
        assert [e["path"] for e in immediate_entries] == [modified_entry["path"]]
        assert result["files_added"] == 0
        assert modified_entry["path"] not in _removed_paths(ctx.mocks.remove_deleted)
        assert (STATE_HYDRATED, STATE_NOT_HYDRATED) in [
            call.args[2:4] for call in ctx.mocks.transition_song_state.call_args_list
        ]


@pytest.mark.unit
@pytest.mark.mocked
class TestFolderWalkRetry:
    def test_folder_retry_then_success_reconciles_folder(self, workflow: tuple[Any, Any]) -> None:
        """Attempt 0 raises but attempt 1 succeeds: the folder walk is retried, the
        folder is reconciled (its missing rows become delete candidates), it is not
        counted failed, and it is not treated as unreconciled."""
        module, callable_ = workflow
        old = _song("/music/flaky/old.flac", "flaky/old.flac", "cp-old")
        with _patched_scan(
            module,
            folders=[_folder("flaky")],
            existing={"flaky": {old.path: _carrier(old)}},
            batches={"/music/flaky": _batch(discovered=set())},
            folder_transient_errors={"/music/flaky": OSError("transient walk failure")},
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        # The walk was attempted twice: first failure, then success.
        assert ctx.mocks.scan_folder_files.call_count == 2
        # Reconciled: the missing row is removed and the folder is not failed.
        assert old.path in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_failed"] == 0
        assert result["files_removed"] == 1
        assert result["warnings"] == []


@pytest.mark.unit
@pytest.mark.mocked
class TestSourceStillPresent:
    def test_unreconciled_root_folder_rejects_nested_and_accepts_top_level(self) -> None:
        """The root folder ``""`` as an unreconciled path rejects a nested
        ``normalized_path`` (it belongs to the root) and accepts a top-level one."""
        assert quick_wf._source_still_present("sub/dir/track.flac", "/music/sub/dir/track.flac", set(), {""}) is False
        assert full_wf._source_still_present("sub/dir/track.flac", "/music/sub/dir/track.flac", set(), {""}) is False
        assert quick_wf._source_still_present("track.flac", "/music/track.flac", set(), {""}) is True
        assert full_wf._source_still_present("track.flac", "/music/track.flac", set(), {""}) is True

    def test_discovered_path_is_present_and_other_folder_is_not(self) -> None:
        """A discovered source is present; a source in an unrelated folder is not."""
        assert quick_wf._source_still_present("f1/a.flac", "/music/f1/a.flac", {"/music/f1/a.flac"}, set()) is True
        assert full_wf._source_still_present("f1/a.flac", "/music/f1/a.flac", {"/music/f1/a.flac"}, set()) is True
        assert quick_wf._source_still_present("other/a.flac", "/music/other/a.flac", set(), {"f1"}) is False
        assert full_wf._source_still_present("other/a.flac", "/music/other/a.flac", set(), {"f1"}) is False


@pytest.mark.unit
@pytest.mark.mocked
class TestDbFallbackGuardUnreconciledFolders:
    def test_db_fallback_rejects_match_to_source_in_cached_folder(self) -> None:
        """A DB chromaprint match whose source lives in an unchanged cached folder
        must not be relocated: the cached folder was not walked, so the source is
        still present on disk and the new file is inserted instead."""
        module, callable_ = quick_wf, quick_wf.scan_library_quick_workflow
        cached = _song("/music/cached/live.flac", "cached/live.flac", "cp-move")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        trigger = _song("/music/f1/trigger.flac", "f1/trigger.flac", "cp-trigger")
        with _patched_scan(
            module,
            folders=[_folder("cached"), _folder("f1")],
            existing={"cached": {cached.path: _carrier(cached)}, "f1": {trigger.path: _carrier(trigger)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            cached_folders={"cached": _cached_folder("cached")},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidate=cached,
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert cached.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1

    def test_db_fallback_rejects_match_to_source_in_folder_that_failed_walk(self, workflow: tuple[Any, Any]) -> None:
        """A folder whose walk failed after the retry contributes no discovered
        paths or missing candidates, so its live rows must be treated as unknown:
        a DB-fallback match sourced there is not applied and the new file is
        inserted."""
        module, callable_ = workflow
        live = _song("/music/broken/live.flac", "broken/live.flac", "cp-move")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        trigger = _song("/music/f1/trigger.flac", "f1/trigger.flac", "cp-trigger")
        with _patched_scan(
            module,
            folders=[_folder("broken"), _folder("f1")],
            existing={"broken": {live.path: _carrier(live)}, "f1": {trigger.path: _carrier(trigger)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            folder_errors={"/music/broken": OSError("walk failed")},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidate=live,
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert live.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1
