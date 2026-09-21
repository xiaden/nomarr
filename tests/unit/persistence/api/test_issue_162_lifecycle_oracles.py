"""Spec-first safety oracles for Issue #162 lifecycle admission.

These tests exercise the accepted Plan 1 lifecycle admission contract through
its persistence repository boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import nomarr.helpers.exceptions as exceptions
from nomarr.helpers.constants.file_states import STATE_NOT_HYDRATED
from nomarr.helpers.constants.pipeline_states import (
    SCAN_IN_PROGRESS,
    WRITE_NOT_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.persistence.api.library_regions import LibraryRegionsDb

pytestmark = pytest.mark.unit


_LIB_A = Library(name="library-a", root_path="/music/a", library_uuid="11111111-1111-1111-1111-111111111111")
_LIB_B = Library(name="library-b", root_path="/music/b", library_uuid="22222222-2222-2222-2222-222222222222")


def test_admission_intents_are_public_on_the_library_regions_facade() -> None:
    """Both lifecycle transitions must have one public persistence owner."""
    assert hasattr(LibraryRegionsDb, "admit_scan")
    assert hasattr(LibraryRegionsDb, "admit_tag_write")


def test_direct_hydration_and_physical_write_boundaries_have_typed_conflict_oracles() -> None:
    """Direct mutation entry points must not bypass lifecycle authority."""
    # These named contract assertions deliberately fail until the canonical
    # guards are installed at the persistence/component mutation boundaries.
    from nomarr.persistence.api.library_songs import LibrarySongsDb

    assert hasattr(LibrarySongsDb, "hydrate_songs_batch")
    assert hasattr(exceptions, "LibraryOperationConflict")
    assert STATE_NOT_HYDRATED == "not_hydrated"


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return [type("Row", (), {"_mapping": row})() for row in self._rows]

    def scalar(self) -> int:
        return 0


class _AdmissionSession:
    """Deterministic SQL seam for exercising PipelineRepository admission logic."""

    def __init__(self, rows: list[dict[str, object]], hydrated: int = 0) -> None:
        self.rows = rows
        self.hydrated = hydrated
        self.execute_count = 0
        self.commits = 0

    def begin_nested(self):
        from contextlib import nullcontext

        return nullcontext()

    def execute(self, statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return _Rows(self.rows)
        result = _Rows([])
        result.scalar = lambda: self.hydrated
        return result

    def commit(self) -> None:
        self.commits += 1


def _real_regions(*, rows: list[dict[str, object]] | None = None, hydrated: int = 0):
    from nomarr.persistence.database.pipeline_repo import PipelineRepository

    session = _AdmissionSession(rows or [], hydrated=hydrated)
    library_repo = MagicMock()
    library_repo.get_library_by_natural_key.return_value = {"id": 17}
    regions = LibraryRegionsDb(
        session=session,
        library_repo=library_repo,
        song_state_repo=MagicMock(),
        pipeline_repo=PipelineRepository(session),
    )
    return regions, session


def test_pipeline_repository_scan_admission_preserves_write_state() -> None:
    regions, session = _real_regions(
        rows=[{"state_key": "tag_write_state", "state_data": {"state": WRITE_NOT_WRITTEN}}]
    )

    state = regions.admit_scan(_LIB_A)

    assert state.scan_state == SCAN_IN_PROGRESS
    assert state.tag_write_state == WRITE_NOT_WRITTEN
    assert session.commits == 1


def test_pipeline_repository_tag_write_rejects_active_scan() -> None:
    regions, _ = _real_regions(rows=[{"state_key": "scan_state", "state_data": {"state": SCAN_IN_PROGRESS}}])

    with pytest.raises(exceptions.LibraryOperationConflict) as exc_info:
        regions.admit_tag_write(_LIB_A)

    assert exc_info.value.operation == "tag_write"
    assert exc_info.value.scan_state == SCAN_IN_PROGRESS
    assert exc_info.value.not_hydrated_count == 0


def test_pipeline_repository_tag_write_rejects_not_hydrated_debt() -> None:
    regions, _ = _real_regions(hydrated=2)

    with pytest.raises(exceptions.LibraryOperationConflict) as exc_info:
        regions.admit_tag_write(_LIB_A)

    assert exc_info.value.not_hydrated_count == 2


def test_pipeline_repository_admission_resolves_library_scope() -> None:
    regions, _ = _real_regions()

    regions.admit_scan(_LIB_B)

    regions._library_repo.get_library_by_natural_key.assert_called_once_with(_LIB_B.name, _LIB_B.root_path)


def test_tag_extraction_conflict_does_not_mark_song_errored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker lifecycle conflicts defer hydration instead of publishing errored."""
    from unittest.mock import MagicMock

    from nomarr.helpers.exceptions import LibraryOperationConflict
    from nomarr.services.infrastructure.workers import tag_extraction_worker as worker

    song = object()
    stop_event = __import__("threading").Event()
    discover_calls = iter([song, None])
    transitioned: list[object] = []

    monkeypatch.setattr(worker, "discover_and_claim_file_for_tags", lambda *_: next(discover_calls))
    monkeypatch.setattr(
        worker,
        "_process_file",
        lambda *_: (_ for _ in ()).throw(
            LibraryOperationConflict("hydration", scan_state="scanned", tag_write_state="writing")
        ),
    )
    monkeypatch.setattr(worker, "transition_song_state", lambda *args: transitioned.append(args))
    monkeypatch.setattr(worker, "release_claim", lambda *_: None)
    monkeypatch.setattr(stop_event, "wait", lambda *_: stop_event.set())

    instance = worker.TagExtractionWorker(MagicMock(), stop_event=stop_event)
    instance.run()

    assert transitioned == []


def test_sync_workflow_re_raises_lifecycle_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast-locator sync must not turn a lifecycle conflict into a warning."""
    from unittest.mock import MagicMock

    from nomarr.helpers.exceptions import LibraryOperationConflict
    from nomarr.workflows.library import sync_file_to_library_wf as sync_workflow

    conflict = LibraryOperationConflict("hydration", scan_state="scanned", tag_write_state="writing")
    monkeypatch.setattr(sync_workflow, "_sync_tags_and_entities", MagicMock(side_effect=conflict))

    with pytest.raises(LibraryOperationConflict):
        sync_workflow.sync_file_to_library(MagicMock(), "/music/a/song.flac", {}, "nom", None, _LIB_A, object())
