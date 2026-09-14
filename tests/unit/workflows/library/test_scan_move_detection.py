"""Behavioral regressions for move detection in the library scan workflows.

Both ``scan_library_quick_workflow`` and ``scan_library_full_workflow`` must
reconcile detected relocations *before* treating a missing path as a delete and a
newly discovered path as an insert. These tests drive the real
``detect_move_for_new_file`` / ``relocate_song`` component (only chromaprint
decoding and the bounded DB candidate lookup are stubbed) through the workflow so
the wiring itself is exercised:

* moves within one changed folder,
* moves across two changed folders,
* moves from a folder that vanished entirely into a discovered location,
* the bounded DB-candidate lookup for otherwise-unmatched new files, and its
  rejection when the matched source is still present on disk,
* multi-move / multi-new batches reconciled per file,
* quick-scan skipping of unchanged cached folders,
* one chromaprint decode per genuine new file (bounded, never whole-library),
* negatives: a genuinely new file is still inserted, and a genuinely missing
  file is still removed.

The bounded design no longer holds a whole-library in-memory candidate set; the
per-new-file lookup is authoritative and every genuine new file computes its own
chromaprint exactly once.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock, patch

import pytest

import nomarr.components.library.move_detection_comp as move_comp
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
from nomarr.helpers.dataclasses.song_dataclass import ChromaprintSongMatches, Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate

if TYPE_CHECKING:
    from collections.abc import Iterator

_MOVEMENT_MODULE = "nomarr.components.library.move_detection_comp"

# The production persistence window is the first ``limit`` rows; the repository
# fetches one sentinel row beyond it to detect truncation.
_NOMINAL_CANDIDATE_LIMIT = 50

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


def _entry(path: str, normalized_path: str, *, duration: float | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "path": path,
        "normalized_path": normalized_path,
        "file_size": 2048,
        "modified_time": 9999,
        "scanned_at": 1,
    }
    if duration is not None:
        entry["duration_seconds"] = duration
    return entry


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
    db_candidates: list[Song] | None = None,
    candidates_complete: bool = True,
    cached_folders: dict[str, SimpleNamespace] | None = None,
    folder_errors: dict[str, Exception] | None = None,
    folder_transient_errors: dict[str, Exception] | None = None,
    present_paths: set[str] | None = None,
    spy_detect: bool = False,
) -> Iterator[SimpleNamespace]:
    """Patch one scan workflow module and the move-detection chromaprint edges.

    ``existing`` maps a folder rel path to its mutable DB carrier map; ``batches``
    maps a folder absolute path to the ``FileBatchResult`` the scan returns. Only
    the expensive chromaprint decode and the bounded DB candidate lookup are
    stubbed; move matching/application runs for real against a mocked ``Database``.

    ``present_paths`` models on-disk presence for the workflow's patchable
    ``_path_exists``. It defaults to the union of every batch's ``discovered_paths``
    (so undiscovered persisted rows are genuinely absent). Because a move removes the
    row from its old normalized folder, a successful ``move_library_song`` removes
    the source carrier from the per-folder mapping — mirroring production, where
    the exact-folder walk accessor no longer returns a relocated row under its old
    folder.

    ``cached_folders`` seeds the quick-scan folder cache so unchanged folders can be
    skipped. ``folder_errors`` maps a folder absolute path to an exception raised on
    every walk attempt; ``folder_transient_errors`` raises only on the first attempt.
    ``spy_detect`` patches the workflow's ``detect_move_for_new_file`` with a spy that
    calls the real function, exposing it as ``mocks.detect``.
    """
    db = MagicMock()
    db.library = MagicMock()
    db.library.count_songs_for_library.return_value = 0

    candidates = db_candidates or []

    def _destination(command: Any) -> SongIdentity:
        # Persistence semantics: after a move the source row no longer lives under
        # its old normalized folder, so the carrier is removed from the per-folder
        # mapping. Cleanup therefore must not re-delete a relocated row.
        source_normalized = command.song_identity.normalized_path
        for folder_map in existing.values():
            for key, carrier in list(folder_map.items()):
                if carrier.candidate.song.normalized_path == source_normalized:
                    del folder_map[key]
                    break
        return SongIdentity(library=command.song_identity.library, normalized_path=command.scan.normalized_path)

    db.library.move_library_song.side_effect = _destination

    chromaprints = chromaprint_by_path or {}
    errors = folder_errors or {}
    transient_errors = folder_transient_errors or {}
    transient_attempts: dict[str, int] = {}
    discovered = set()
    for batch in batches.values():
        discovered |= batch.discovered_paths
    present = set(present_paths) if present_paths is not None else set(discovered)

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

    exact_returns: list[tuple[str, dict[str, StateTaggedSong]]] = []

    def _exact_folder_rows(rel: str) -> dict[str, StateTaggedSong]:
        # Production ``get_songs_in_exact_folder`` returns only the requested
        # folder's direct members. Model that so the per-folder WALK working set
        # never includes nested descendant rows.
        rows = dict(existing.get(rel, {}))
        exact_returns.append((rel, rows))
        return rows

    def _songs_page(after_normalized_path: str | None, limit: int) -> list[Song]:
        # Production ``list_songs_after_normalized_path`` returns one bounded page
        # of the library's songs ordered by ``normalized_path``. Model that over ALL
        # carriers currently in ``existing`` (a relocated carrier is removed from
        # its source folder), honoring the exclusive cursor and the limit.
        rows = [carrier.candidate.song for folder_map in existing.values() for carrier in folder_map.values()]
        rows.sort(key=lambda song: song.normalized_path)
        if after_normalized_path is not None:
            rows = [song for song in rows if song.normalized_path > after_normalized_path]
        return rows[:limit]

    def _songs_page_call(_library: Any, *, after_normalized_path: str | None, limit: int) -> list[Song]:
        return _songs_page(after_normalized_path, limit)

    db.library.list_songs_after_normalized_path.side_effect = _songs_page_call

    mocks = SimpleNamespace()
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "resolve_library_for_scan", return_value=_LIBRARY))
        stack.enter_context(patch.object(module, "validate_library_root"))
        stack.enter_context(patch.object(module, "get_folder_rel_paths", return_value=db_folder_paths or set()))
        stack.enter_context(patch.object(module, "get_cached_folders", return_value=cached_folders or {}))
        stack.enter_context(patch.object(module, "discover_library_folders", return_value=folders))
        mocks.get_songs_in_exact_folder = stack.enter_context(
            patch.object(
                module, "get_songs_in_exact_folder", side_effect=lambda _db, _lib, rel: _exact_folder_rows(rel)
            )
        )
        mocks.get_songs_page = db.library.list_songs_after_normalized_path
        mocks.exact_returns = exact_returns
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

        # Model on-disk presence deterministically for the workflow's cleanup and
        # candidate-source checks (both read the module-global ``_path_exists``).
        stack.enter_context(patch.object(module, "_path_exists", side_effect=lambda path: path in present))

        stack.enter_context(patch(f"{_MOVEMENT_MODULE}.build_library_path_from_input", side_effect=_fake_library_path))
        mocks.compute_chromaprint = stack.enter_context(
            patch(f"{_MOVEMENT_MODULE}.compute_chromaprint_for_file", side_effect=_compute)
        )

        def _candidates(_db: Any, _lib: Any, chromaprint: str) -> ChromaprintSongMatches:
            matched = [c for c in candidates if c.chromaprint == chromaprint]
            if candidates_complete:
                return ChromaprintSongMatches(songs=tuple(matched), complete=True)
            # Truncated lookup: only the nominal window is visible; the sentinel
            # row (matched[limit]) stays hidden behind ``complete=False``.
            return ChromaprintSongMatches(songs=tuple(matched[:_NOMINAL_CANDIDATE_LIMIT]), complete=False)

        stack.enter_context(patch(f"{_MOVEMENT_MODULE}.find_move_candidates_by_chromaprint", side_effect=_candidates))
        if spy_detect:
            mocks.detect = stack.enter_context(
                patch.object(module, "detect_move_for_new_file", side_effect=move_comp.detect_move_for_new_file)
            )

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
            db_candidates=[old],
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
            db_candidates=[old],
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
            db_candidates=[old],
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "gone/old.flac"
        assert command.new_path == "/music/fresh/new.flac"
        assert new["path"] not in _upsert_paths(ctx.mocks.upsert)
        assert old.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 1

    def test_db_candidate_lookup_detects_move_for_unmatched_new_file(self, workflow: tuple[Any, Any]) -> None:
        """A new file is looked up per-file in the DB and moved instead of
        inserted, when the matched source is genuinely absent from disk."""
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
            db_candidates=[vanished],
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

    def test_db_candidate_lookup_rejects_match_to_still_present_source(self, workflow: tuple[Any, Any]) -> None:
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
            db_candidates=[live],
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
            db_candidates=[old],
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        assert _scanned_paths(ctx.mocks.scan_folder_files) == {"/music/f1"}
        walked_folders = {call.args[2] for call in ctx.mocks.get_songs_in_exact_folder.call_args_list}
        assert "cached" not in walked_folders
        assert stale.path not in _removed_paths(ctx.mocks.remove_deleted)
        ctx.db.library.move_library_song.assert_called_once()
        command = ctx.db.library.move_library_song.call_args.args[0]
        assert command.song_identity.normalized_path == "f1/old.flac"
        assert result["files_moved"] == 1
        assert result["folders_skipped"] == 1

    def test_new_file_chromaprint_computed_once_and_inserted(self, workflow: tuple[Any, Any]) -> None:
        """Every genuine new file computes its chromaprint exactly once, misses the
        bounded lookup, and is inserted; the chromaprint-less missing row is removed."""
        module, callable_ = workflow
        old = _song("/music/f1/old.flac", "f1/old.flac", None)
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {old.path: _carrier(old)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            chromaprint_by_path={new["path"]: "cp-new"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        ctx.mocks.compute_chromaprint.assert_called_once()
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
            db_candidates=[old_a, old_b],
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
            chromaprint_by_path={new_entry["path"]: "cp-new"},
        ) as ctx:
            result = self._run(module, callable_, ctx.db)

        # Two upsert calls: the modified entry immediately, the new entry deferred.
        assert len(ctx.mocks.upsert_returns) == 2
        immediate_entries, modified_identities = ctx.mocks.upsert_returns[0]
        deferred_entries, _ = ctx.mocks.upsert_returns[1]
        assert [e["path"] for e in immediate_entries] == [modified_entry["path"]]
        assert [e["path"] for e in deferred_entries] == [new_entry["path"]]
        # The modified path never reaches the deferred insert.
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
        # The scanner's updated metadata is carried through unchanged (metadata update).
        assert immediate_entries[0]["modified_time"] == modified_entry["modified_time"]
        assert immediate_entries[0]["file_size"] == modified_entry["file_size"]
        assert immediate_entries[0]["scanned_at"] == modified_entry["scanned_at"]
        assert result["files_added"] == 0
        assert result["files_moved"] == 0
        # A changed-in-place file keeps its locator: it is never a move candidate and
        # never deleted/recreated, and no chromaprint is computed for it.
        ctx.db.library.move_library_song.assert_not_called()
        ctx.mocks.compute_chromaprint.assert_not_called()
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
class TestCandidateSourcePresent:
    """``_candidate_source_present`` decides whether a chromaprint candidate may
    still be a relocation origin: only a genuinely absent source qualifies."""

    def test_unreconciled_root_folder_presumes_present_even_when_absent(self) -> None:
        """The root folder ``""`` as an unreconciled path short-circuits a root-level
        ``normalized_path`` (parent ``""``) to present regardless of disk state."""
        root_song = _song("/music/track.flac", "track.flac", "cp")
        nested_song = _song("/music/sub/dir/track.flac", "sub/dir/track.flac", "cp")
        for module in (quick_wf, full_wf):
            with patch.object(module, "_path_exists", return_value=False):
                assert module._candidate_source_present(root_song, {""}) is True
                assert module._candidate_source_present(root_song, set()) is False
                assert module._candidate_source_present(nested_song, {""}) is False

    def test_present_path_is_present_and_absent_path_is_not(self) -> None:
        song = _song("/music/f1/a.flac", "f1/a.flac", "cp")
        for module in (quick_wf, full_wf):
            with patch.object(module, "_path_exists", return_value=True):
                assert module._candidate_source_present(song, set()) is True
            with patch.object(module, "_path_exists", return_value=False):
                assert module._candidate_source_present(song, set()) is False

    def test_unreconciled_parent_folder_short_circuits_absent_path(self) -> None:
        song = _song("/music/f1/a.flac", "f1/a.flac", "cp")
        for module in (quick_wf, full_wf):
            with patch.object(module, "_path_exists", return_value=False):
                assert module._candidate_source_present(song, {"f1"}) is True


@pytest.mark.unit
@pytest.mark.mocked
class TestDbCandidateGuardUnreconciledFolders:
    def test_rejects_match_to_source_in_cached_folder(self) -> None:
        """A chromaprint match whose source lives in an unchanged cached folder must
        not be relocated: the cached folder was not walked, so the source is still
        present and the new file is inserted instead."""
        cached = _song("/music/cached/live.flac", "cached/live.flac", "cp-move")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        trigger = _song("/music/f1/trigger.flac", "f1/trigger.flac", "cp-trigger")
        with _patched_scan(
            quick_wf,
            folders=[_folder("cached"), _folder("f1")],
            existing={"cached": {cached.path: _carrier(cached)}, "f1": {trigger.path: _carrier(trigger)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            cached_folders={"cached": _cached_folder("cached")},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidates=[cached],
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert cached.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1

    def test_rejects_match_to_source_in_folder_that_failed_walk(self, workflow: tuple[Any, Any]) -> None:
        """A folder whose walk failed after the retry contributes no discoveries, so
        its live rows must be treated as unknown: a match sourced there is not applied
        and the new file is inserted."""
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
            db_candidates=[live],
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert live.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryRootRemap:
    def test_root_remap_rebases_same_locator_with_zero_chromaprint(self, workflow: tuple[Any, Any]) -> None:
        """A library-root/mount remap changes every absolute path while the
        normalized paths (the identities) stay fixed. Each row is rebased in place
        by its unchanged locator: no chromaprint decode, no insert, no deletion."""
        module, callable_ = workflow
        count = 12
        rows = [_song(f"/music/album/track{i}.flac", f"album/track{i}.flac", f"cp-{i}") for i in range(count)]
        entries = [_entry(f"/newroot/album/track{i}.flac", f"album/track{i}.flac") for i in range(count)]
        with _patched_scan(
            module,
            folders=[_folder("album", file_count=count)],
            existing={"album": {row.path: _carrier(row) for row in rows}},
            batches={
                "/music/album": _batch(entries=entries, discovered={e["path"] for e in entries}),
            },
        ) as ctx:
            result = self._run_root_remap(callable_, ctx.db)

        assert ctx.mocks.compute_chromaprint.call_count == 0
        assert ctx.db.library.move_library_song.call_count == count
        for call in ctx.db.library.move_library_song.call_args_list:
            command = call.args[0]
            assert command.song_identity.normalized_path.startswith("album/track")
            assert command.new_path.startswith("/newroot/album/track")
        ctx.mocks.upsert.assert_not_called()
        ctx.mocks.remove_deleted.assert_not_called()
        assert result["files_moved"] == count

    @staticmethod
    def _run_root_remap(callable_: Any, db: MagicMock) -> dict[str, Any]:
        return cast("dict[str, Any]", callable_(db, _LIBRARY, tagger_version="v1"))


@pytest.mark.unit
@pytest.mark.mocked
class TestSameLocatorRebaseFallthrough:
    def test_rebase_failure_falls_through_to_new_insert(self, workflow: tuple[Any, Any]) -> None:
        """A same-locator entry (unchanged normalized path, changed absolute path)
        whose rebase fails because the source locator is stale/missing must not be
        silently dropped: no move is applied, the file still reaches the deferred
        insert, and it is counted as added."""
        module, callable_ = workflow
        old = _song("/music/f1/old.flac", "f1/old.flac", "cp-old")
        remapped = _entry("/newroot/f1/old.flac", "f1/old.flac")
        with (
            _patched_scan(
                module,
                folders=[_folder("f1")],
                existing={"f1": {old.path: _carrier(old)}},
                batches={"/music/f1": _batch(entries=[remapped], discovered={remapped["path"]})},
                chromaprint_by_path={remapped["path"]: "cp-old"},
            ) as ctx,
            patch.object(module, "relocate_song", return_value=False),
        ):
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert remapped["path"] in _upsert_paths(ctx.mocks.upsert)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestMassRenameBounded:
    def test_removed_bulk_move_symbols_do_not_exist(self) -> None:
        """The whole-library bulk move surface is gone from every layer."""
        for module in (quick_wf, full_wf, move_comp):
            assert not hasattr(module, "detect_file_moves")
        assert not hasattr(move_comp, "apply_detected_moves")
        assert not hasattr(move_comp, "detect_file_move_via_db")
        assert not hasattr(move_comp, "MoveDetectionResult")
        assert not hasattr(move_comp, "find_move_candidate_by_chromaprint")

    def test_detect_called_once_per_genuine_new_entry(self, workflow: tuple[Any, Any]) -> None:
        """Move detection is bounded per genuine new entry — never once over a
        whole-library candidate set. A batch of two new files with five unrelated
        persisted rows calls the detector exactly twice."""
        module, callable_ = workflow
        known = [_song(f"/music/f1/keep{i}.flac", f"f1/keep{i}.flac", f"cp-keep{i}") for i in range(5)]
        new_entries = [
            _entry("/music/f1/new-a.flac", "f1/new-a.flac"),
            _entry("/music/f1/new-b.flac", "f1/new-b.flac"),
        ]
        with _patched_scan(
            module,
            folders=[_folder("f1", file_count=len(known) + len(new_entries))],
            existing={"f1": {song.path: _carrier(song) for song in known}},
            batches={
                "/music/f1": _batch(entries=new_entries, discovered={e["path"] for e in new_entries}),
            },
            chromaprint_by_path={entry["path"]: f"cp-new-{i}" for i, entry in enumerate(new_entries)},
            spy_detect=True,
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        assert ctx.mocks.detect.call_count == len(new_entries)
        assert result["files_added"] == len(new_entries)
        assert result["files_moved"] == 0


@pytest.mark.unit
@pytest.mark.mocked
class TestLiveDuplicate:
    def test_live_duplicate_with_identical_chromaprint_inserted_distinct(self, workflow: tuple[Any, Any]) -> None:
        """A chromaprint collision whose source is still present on disk is a live
        duplicate/copy, not a move: the new file is inserted, no move is applied,
        and the live row is never removed."""
        module, callable_ = workflow
        live = _song("/music/f1/live.flac", "f1/live.flac", "cp-dup")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {live.path: _carrier(live)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            db_candidates=[live],
            chromaprint_by_path={new["path"]: "cp-dup"},
            present_paths={live.path, new["path"]},
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert live.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1
        assert result["files_removed"] == 0


@pytest.mark.unit
@pytest.mark.mocked
class TestAmbiguousRelocation:
    def test_multiple_absent_candidates_do_not_cause_an_arbitrary_move(self, workflow: tuple[Any, Any]) -> None:
        """Two absent rows sharing the new file's chromaprint are ambiguous: no
        arbitrary pick is applied, the new file is inserted, and both stale rows
        are cleaned up."""
        module, callable_ = workflow
        src_a = _song("/music/f1/a.flac", "f1/a.flac", "cp-amb")
        src_b = _song("/music/f1/b.flac", "f1/b.flac", "cp-amb")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {src_a.path: _carrier(src_a), src_b.path: _carrier(src_b)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            db_candidates=[src_a, src_b],
            chromaprint_by_path={new["path"]: "cp-amb"},
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert {src_a.path, src_b.path} <= _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestTruncatedCandidateWindow:
    def test_truncated_window_with_one_visible_absent_candidate_does_not_relocate(
        self, workflow: tuple[Any, Any]
    ) -> None:
        """More than the nominal 50 same-chromaprint rows exist: the visible window
        holds exactly one absent candidate, while the sentinel row hiding another
        absent row sits outside the nominal window. Because the population is
        truncated, no automatic relocation may occur even though exactly one absent
        survivor is visible."""
        module, callable_ = workflow
        visible_absent = _song("/music/f1/visible.flac", "f1/visible.flac", "cp-many")
        visible_live = [
            _song(f"/music/f1/live{i}.flac", f"f1/live{i}.flac", "cp-many") for i in range(_NOMINAL_CANDIDATE_LIMIT - 1)
        ]
        outside_absent = _song("/music/f1/outside.flac", "f1/outside.flac", "cp-many")
        new = _entry("/music/f1/new.flac", "f1/new.flac")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"f1": {visible_absent.path: _carrier(visible_absent)}},
            batches={"/music/f1": _batch(entries=[new], discovered={new["path"]})},
            db_candidates=[*visible_live, visible_absent, outside_absent],
            candidates_complete=False,
            chromaprint_by_path={new["path"]: "cp-many"},
            present_paths={c.path for c in visible_live} | {new["path"]},
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert result["files_moved"] == 0
        assert result["files_added"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestDeletionScoping:
    def test_quick_scan_never_cleans_cache_skipped_folder_rows(self) -> None:
        """A no-op/cache-skipped folder's rows are never deleted, while a changed
        folder's genuinely absent rows are."""
        cached_row = _song("/music/cached/stale.flac", "cached/stale.flac", "cp-cached")
        changed_row = _song("/music/f1/gone.flac", "f1/gone.flac", "cp-gone")
        with _patched_scan(
            quick_wf,
            folders=[_folder("cached"), _folder("f1")],
            existing={
                "cached": {cached_row.path: _carrier(cached_row)},
                "f1": {changed_row.path: _carrier(changed_row)},
            },
            batches={"/music/f1": _batch(discovered=set())},
            cached_folders={"cached": _cached_folder("cached")},
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert changed_row.path in removed
        assert cached_row.path not in removed
        assert result["files_removed"] == 1

    def test_full_scan_never_cleans_folder_that_failed_walk(self) -> None:
        """A folder whose walk fails both attempts is unreconciled and stays out of
        the cleanup scope, while a successfully-walked folder's absent rows are
        removed."""
        broken_row = _song("/music/broken/live.flac", "broken/live.flac", "cp-broken")
        changed_row = _song("/music/f1/gone.flac", "f1/gone.flac", "cp-gone")
        with _patched_scan(
            full_wf,
            folders=[_folder("broken"), _folder("f1")],
            existing={
                "broken": {broken_row.path: _carrier(broken_row)},
                "f1": {changed_row.path: _carrier(changed_row)},
            },
            batches={"/music/f1": _batch(discovered=set())},
            folder_errors={"/music/broken": OSError("walk failed")},
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert changed_row.path in removed
        assert broken_row.path not in removed
        assert result["files_removed"] == 1

    def test_reconciled_ancestor_never_cleans_nested_skipped_child_rows(self) -> None:
        """Cleanup reads only the reconciled ancestor's direct members via
        ``get_songs_in_exact_folder``, so a nested descendant folder is never part
        of its lookup. A genuinely-absent row whose own folder is a cache-skipped
        child must not be deleted, while an absent row directly in the reconciled
        ancestor is."""
        child_row = _song("/music/parent/child/stale.flac", "parent/child/stale.flac", "cp-child")
        parent_row = _song("/music/parent/gone.flac", "parent/gone.flac", "cp-parent")
        with _patched_scan(
            quick_wf,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={"/music/parent": _batch(discovered=set())},
            cached_folders={"parent/child": _cached_folder("parent/child")},
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert parent_row.path in removed
        assert child_row.path not in removed
        assert result["files_removed"] == 1

    def test_reconciled_ancestor_never_cleans_nested_failed_child_rows(self) -> None:
        """The same exact-folder ancestor-cleanup scoping holds for a nested child
        whose walk FAILED: cleanup reads only the ancestor's direct members, so the
        nested child's absent row is never read or deleted, while the absent row
        directly in the reconciled ancestor is."""
        child_row = _song("/music/parent/child/stale.flac", "parent/child/stale.flac", "cp-child")
        parent_row = _song("/music/parent/gone.flac", "parent/gone.flac", "cp-parent")
        with _patched_scan(
            full_wf,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={"/music/parent": _batch(discovered=set())},
            folder_errors={"/music/parent/child": OSError("walk failed")},
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert parent_row.path in removed
        assert child_row.path not in removed
        assert result["files_removed"] == 1

    def test_vanished_folder_absent_rows_are_deleted_by_cleanup(self, workflow: tuple[Any, Any]) -> None:
        """AC3 (``quick = changed + vanished``): a vanished folder's genuinely absent
        persisted row must be removed by the deferred cleanup pass. The vanished
        folder is never walked, so its absence is established only by the loop over
        ``(*reconciled_folder_paths, *vanished_folder_paths)``; if that loop iterated
        only ``reconciled_folder_paths``, ``rel_path="gone"`` would never be visited
        and the phantom row would survive."""
        module, callable_ = workflow
        gone = _song("/music/gone/old.flac", "gone/old.flac", "cp-gone")
        with _patched_scan(
            module,
            folders=[_folder("f1")],
            existing={"gone": {gone.path: _carrier(gone)}, "f1": {}},
            batches={"/music/f1": _batch(discovered=set())},
            db_folder_paths={"gone"},
            present_paths=set(),
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        # Falsifiable regression: dropping ``vanished_folder_paths`` from the cleanup
        # loop at scan_library_quick_wf.py:319 / scan_library_full_wf.py:307 makes
        # this first assertion fail.
        assert gone.path in _removed_paths(ctx.mocks.remove_deleted)
        ctx.db.library.move_library_song.assert_not_called()
        assert result["files_moved"] == 0
        assert result["files_added"] == 0
        assert result["files_removed"] == 1


@pytest.mark.unit
@pytest.mark.mocked
class TestExactFolderWalkWorkingSet:
    """The per-folder walk AND the deferred cleanup working set are each bounded to
    direct members of exactly one folder. Both use the exact-folder read, so a
    nested descendant subtree is never re-materialized by an ancestor. Genuinely
    untracked parents are recovered only by the full-scan bounded orphan sweep."""

    def test_nested_folders_cleanup_reads_only_exact_direct_members(self, workflow: tuple[Any, Any]) -> None:
        """Nested audio-bearing folders all scanned with no deletions: every cleanup
        read is exact to its folder's direct rows, so no ancestor materializes a
        descendant subtree."""
        module, callable_ = workflow
        parent_row = _song("/music/parent/a.flac", "parent/a.flac", "cp-parent")
        child_row = _song("/music/parent/child/b.flac", "parent/child/b.flac", "cp-child")
        with _patched_scan(
            module,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={
                "/music/parent": _batch(discovered={parent_row.path}),
                "/music/parent/child": _batch(discovered={child_row.path}),
            },
            present_paths={parent_row.path, child_row.path},
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        for rel, rows in ctx.mocks.exact_returns:
            if rel == "parent":
                assert set(rows) == {parent_row.path}
            elif rel == "parent/child":
                assert set(rows) == {child_row.path}
        read_paths = {path for _rel, rows in ctx.mocks.exact_returns for path in rows}
        assert read_paths == {parent_row.path, child_row.path}
        assert result["files_removed"] == 0

    def test_parent_and_child_scanned_use_exact_per_folder_working_sets(self, workflow: tuple[Any, Any]) -> None:
        """Parent and child are both walked: each working set contains only its own
        direct members, and the parent's excludes the child's rows."""
        module, callable_ = workflow
        parent_row = _song("/music/parent/a.flac", "parent/a.flac", "cp-parent")
        child_row = _song("/music/parent/child/b.flac", "parent/child/b.flac", "cp-child")
        with _patched_scan(
            module,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={
                "/music/parent": _batch(discovered={parent_row.path}),
                "/music/parent/child": _batch(discovered={child_row.path}),
            },
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        walked = {rel: set(rows) for rel, rows in ctx.mocks.exact_returns}
        assert walked["parent"] == {parent_row.path}
        assert walked["parent/child"] == {child_row.path}
        assert child_row.path not in walked["parent"]
        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert parent_row.path not in removed
        assert child_row.path not in removed
        assert result["files_removed"] == 0

    def test_parent_scanned_child_cache_skipped_preserves_child_rows(self) -> None:
        """A reconciled parent's working set excludes a cache-skipped child's rows,
        and those child rows stay untouched by cleanup."""
        parent_row = _song("/music/parent/a.flac", "parent/a.flac", "cp-parent")
        child_row = _song("/music/parent/child/b.flac", "parent/child/b.flac", "cp-child")
        with _patched_scan(
            quick_wf,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={"/music/parent": _batch(discovered={parent_row.path})},
            cached_folders={"parent/child": _cached_folder("parent/child")},
            present_paths={parent_row.path},
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        walked = {rel: set(rows) for rel, rows in ctx.mocks.exact_returns}
        assert walked["parent"] == {parent_row.path}
        assert child_row.path not in walked["parent"]
        assert "parent/child" not in {rel for rel, _ in ctx.mocks.exact_returns}
        assert child_row.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["folders_skipped"] == 1

    def test_parent_scanned_child_walk_failed_preserves_child_rows_and_rejects_move(self) -> None:
        """A parent walk succeeds while a nested child walk fails: the child's rows
        stay out of the parent's working set, are preserved by cleanup, and are not
        eligible move sources. The failing child is discovered first, so its
        unreconciled status is established before the parent's move pass runs."""
        child_row = _song("/music/parent/child/b.flac", "parent/child/b.flac", "cp-move")
        new = _entry("/music/parent/new.flac", "parent/new.flac")
        with _patched_scan(
            full_wf,
            folders=[_folder("parent/child"), _folder("parent")],
            existing={
                "parent": {},
                "parent/child": {child_row.path: _carrier(child_row)},
            },
            batches={"/music/parent": _batch(entries=[new], discovered={new["path"]})},
            folder_errors={"/music/parent/child": OSError("walk failed")},
            chromaprint_by_path={new["path"]: "cp-move"},
            db_candidates=[child_row],
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        walked = {rel: set(rows) for rel, rows in ctx.mocks.exact_returns}
        assert walked["parent"] == set()
        assert child_row.path not in walked["parent"]
        ctx.db.library.move_library_song.assert_not_called()
        assert new["path"] in _upsert_paths(ctx.mocks.upsert)
        assert child_row.path not in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_moved"] == 0

    def test_large_descendant_subtree_not_in_parent_walk_working_set(self, workflow: tuple[Any, Any]) -> None:
        """A large nested subtree under a walked parent is never materialized as the
        parent's walk OR cleanup working set: both use the exact-folder query, so
        the parent is read only for its direct members."""
        module, callable_ = workflow
        direct = _song("/music/parent/a.flac", "parent/a.flac", "cp-a")
        existing: dict[str, dict[str, StateTaggedSong]] = {"parent": {direct.path: _carrier(direct)}}
        present = {direct.path}
        for i in range(300):
            desc = _song(f"/music/parent/sub{i}/t.flac", f"parent/sub{i}/t.flac", None)
            existing[f"parent/sub{i}"] = {desc.path: _carrier(desc)}
            present.add(desc.path)
        with _patched_scan(
            module,
            folders=[_folder("parent", file_count=301)],
            existing=existing,
            batches={"/music/parent": _batch(discovered={direct.path})},
            present_paths=present,
        ) as ctx:
            result = callable_(ctx.db, _LIBRARY, tagger_version="v1")

        # The parent is both walked and cleaned, so its exact read runs more than
        # once; every such read returns ONLY the single direct member.
        parent_reads = [rows for rel, rows in ctx.mocks.exact_returns if rel == "parent"]
        assert parent_reads
        for rows in parent_reads:
            assert set(rows) == {direct.path}
        # No descendant path is ever read by a walk/cleanup working set.
        read_paths = {path for _rel, rows in ctx.mocks.exact_returns for path in rows}
        assert not any(path.startswith("/music/parent/sub") for path in read_paths)
        assert result["files_removed"] == 0

    def test_nested_reconciled_and_vanished_cleanup_deletes_missing_preserves_others(self) -> None:
        """Exact-folder cleanup deletes genuinely-missing direct members under a
        reconciled ancestor and a vanished folder while preserving a skipped
        child's rows."""
        parent_gone = _song("/music/parent/gone.flac", "parent/gone.flac", "cp-pg")
        child_skipped = _song("/music/parent/child/keep.flac", "parent/child/keep.flac", "cp-child")
        vanished = _song("/music/gone/old.flac", "gone/old.flac", "cp-gone")
        with _patched_scan(
            quick_wf,
            folders=[_folder("parent"), _folder("parent/child")],
            existing={
                "parent": {parent_gone.path: _carrier(parent_gone)},
                "parent/child": {child_skipped.path: _carrier(child_skipped)},
                "gone": {vanished.path: _carrier(vanished)},
            },
            batches={"/music/parent": _batch(discovered=set())},
            cached_folders={"parent/child": _cached_folder("parent/child")},
            db_folder_paths={"gone"},
            present_paths=set(),
        ) as ctx:
            result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert parent_gone.path in removed
        assert vanished.path in removed
        assert child_skipped.path not in removed
        assert result["files_removed"] == 2


@pytest.mark.unit
@pytest.mark.mocked
class TestOrphanRecoverySweep:
    """Genuinely-untracked parents are recovered only by the FULL scan's bounded,
    natural-key-paginated sweep; quick scan defers. The sweep holds one page in
    memory and is guarded by the covered set and the unreconciled-ancestor check."""

    def test_full_scan_recovers_stale_song_under_untracked_top_level_folder(self) -> None:
        orphan = _song("/music/untracked/x.flac", "untracked/x.flac", None)
        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing={"scanned": {}, "untracked": {orphan.path: _carrier(orphan)}},
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        assert orphan.path in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_removed"] == 1

    def test_full_scan_recovers_stale_song_beneath_audio_less_ancestors(self) -> None:
        deep = _song("/music/untracked/a/b/c/x.flac", "untracked/a/b/c/x.flac", None)
        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing={"scanned": {}, "untracked/a/b/c": {deep.path: _carrier(deep)}},
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        assert deep.path in _removed_paths(ctx.mocks.remove_deleted)
        assert result["files_removed"] == 1

    def test_folderless_orphan_under_reconciled_ancestor_recovered_by_full_scan(self) -> None:
        """A row under an untracked parent nested beneath a reconciled ancestor is
        no longer surfaced by exact cleanup, but the full-scan sweep recovers it."""
        orphan = _song("/music/parent/orphan/x.flac", "parent/orphan/x.flac", "cp-orphan")
        parent_row = _song("/music/parent/a.flac", "parent/a.flac", "cp-parent")
        with _patched_scan(
            full_wf,
            folders=[_folder("parent")],
            existing={
                "parent": {parent_row.path: _carrier(parent_row)},
                "parent/orphan": {orphan.path: _carrier(orphan)},
            },
            batches={"/music/parent": _batch(discovered={parent_row.path})},
            present_paths={parent_row.path},
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert orphan.path in removed
        assert parent_row.path not in removed
        assert result["files_removed"] == 1

    def test_full_scan_preserves_untracked_nested_row_under_failed_folder(self) -> None:
        """The unreconciled-ancestor guard preserves a row in a nested untracked
        subfolder even when its path is absent, because its ancestor scope failed to
        walk and was not authoritatively inspected."""
        nested = _song("/music/failed/untracked/x.flac", "failed/untracked/x.flac", None)
        failed_row = _song("/music/failed/live.flac", "failed/live.flac", None)
        with _patched_scan(
            full_wf,
            folders=[_folder("failed")],
            existing={
                "failed": {failed_row.path: _carrier(failed_row)},
                "failed/untracked": {nested.path: _carrier(nested)},
            },
            batches={},
            folder_errors={"/music/failed": OSError("walk failed")},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        removed = _removed_paths(ctx.mocks.remove_deleted)
        assert nested.path not in removed
        assert failed_row.path not in removed
        assert result["files_removed"] == 0

    def test_quick_scan_defers_untracked_parent_recovery_to_full_scan(self) -> None:
        orphan = _song("/music/untracked/x.flac", "untracked/x.flac", None)
        with _patched_scan(
            quick_wf,
            folders=[_folder("scanned")],
            existing={"scanned": {}, "untracked": {orphan.path: _carrier(orphan)}},
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            quick_result = quick_wf.scan_library_quick_workflow(ctx.db, _LIBRARY, tagger_version="v1")
        assert orphan.path not in _removed_paths(ctx.mocks.remove_deleted)
        ctx.mocks.get_songs_page.assert_not_called()
        assert quick_result["files_removed"] == 0

        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing={"scanned": {}, "untracked": {orphan.path: _carrier(orphan)}},
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx_full:
            full_result = full_wf.scan_library_full_workflow(ctx_full.db, _LIBRARY, tagger_version="v1")
        assert orphan.path in _removed_paths(ctx_full.mocks.remove_deleted)
        assert full_result["files_removed"] == 1

    def test_orphan_recovery_pages_bounded_with_advancing_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(full_wf, "_ORPHAN_RECOVERY_BATCH_SIZE", 2)
        orphans = [_song(f"/music/o{i}/x.flac", f"o{i}/x.flac", None) for i in range(5)]
        existing: dict[str, dict[str, StateTaggedSong]] = {"scanned": {}}
        existing.update({f"o{i}": {orphans[i].path: _carrier(orphans[i])} for i in range(5)})
        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing=existing,
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        calls = ctx.mocks.get_songs_page.call_args_list
        # Pages of 2, 2, 1 -> three bounded reads, never one materialized library.
        assert len(calls) == 3
        cursors = [call.kwargs["after_normalized_path"] for call in calls]
        assert cursors == [None, "o1/x.flac", "o3/x.flac"]
        assert result["files_removed"] == 5

    def test_orphan_recovery_exact_multiple_terminates_on_empty_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An exact-multiple library terminates on the empty follow-up page.

        With four orphans and a batch size of two the sweep reads pages of 2, 2,
        then an EMPTY page: the final full page must NOT advance the cursor past
        its own last row onto a short page, it must issue one more read that
        returns nothing and terminate via the empty-page branch. Without that
        branch the sweep would index ``page[-1]`` on an empty page.
        """
        monkeypatch.setattr(full_wf, "_ORPHAN_RECOVERY_BATCH_SIZE", 2)
        orphans = [_song(f"/music/o{i}/x.flac", f"o{i}/x.flac", None) for i in range(4)]
        existing: dict[str, dict[str, StateTaggedSong]] = {"scanned": {}}
        existing.update({f"o{i}": {orphans[i].path: _carrier(orphans[i])} for i in range(4)})
        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing=existing,
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        calls = ctx.mocks.get_songs_page.call_args_list
        # Pages of 2, 2, then EMPTY -> three reads; the third proves termination
        # is the empty-page branch, not the short-page branch.
        assert len(calls) == 3
        cursors = [call.kwargs["after_normalized_path"] for call in calls]
        assert cursors == [None, "o1/x.flac", "o3/x.flac"]
        assert result["files_removed"] == 4
        assert _removed_paths(ctx.mocks.remove_deleted) == {orphan.path for orphan in orphans}

    def test_orphan_recovery_empty_library_single_page_no_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A library with no songs yields one empty page, no removals, no error."""
        monkeypatch.setattr(full_wf, "_ORPHAN_RECOVERY_BATCH_SIZE", 2)
        with _patched_scan(
            full_wf,
            folders=[_folder("scanned")],
            existing={"scanned": {}},
            batches={"/music/scanned": _batch(discovered=set())},
            present_paths=set(),
        ) as ctx:
            result = full_wf.scan_library_full_workflow(ctx.db, _LIBRARY, tagger_version="v1")

        calls = ctx.mocks.get_songs_page.call_args_list
        assert len(calls) == 1
        assert calls[0].kwargs["after_normalized_path"] is None
        assert result["files_removed"] == 0
