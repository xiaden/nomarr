"""Integration-style tests for library pipeline orchestration using stateful fakes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_DONE,
    PIPELINE_ML_RUNNING,
    PIPELINE_SCANNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
)
from nomarr.services.domain.tagging_svc import CALIBRATION_APPLY_TASK_ID
from nomarr.services.infrastructure.config_svc import INTERNAL_CALIBRATION_MIN_FILES
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService
from nomarr.services.infrastructure.workers.discovery_worker import _check_idle_pipeline_completion

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.domain.tagging_svc import TaggingService
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService

pytestmark = [pytest.mark.integration, pytest.mark.mocked]


@pytest.fixture(autouse=True)
def pipeline_state_helper_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge helper-based production code to the stateful fake pipeline facade."""

    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_libraries_in_pipeline_state",
        lambda db, state: db.library_pipeline_states.get_libraries_in_state(state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.bulk_transition_pipeline_state",
        lambda db, from_state, to_state: db.library_pipeline_states.bulk_transition(from_state, to_state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.transition_pipeline_state",
        lambda db, library_id, state: db.library_pipeline_states.transition_state(library_id, state),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_pipeline_state",
        lambda db, library_id: db.library_pipeline_states.get_state(library_id),
    )
    monkeypatch.setattr(
        "nomarr.components.library.scan_lifecycle_comp.transition_pipeline_state",
        lambda db, library_id, state: db.library_pipeline_states.transition_state(library_id, state),
    )
    monkeypatch.setattr(
        "nomarr.components.library.library_records_comp.find_ml_complete_libraries",
        lambda db, min_files: db.libraries.find_ml_complete_libraries(min_files),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_library_record",
        lambda db, library_id, **_kwargs: db.libraries.get_library(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.count_untagged_files",
        lambda db, library_id: db.library_files.count_untagged_files(library_id),
    )
    monkeypatch.setattr(
        "nomarr.services.infrastructure.pipeline_svc.get_uncalibrated_tagged_file_ids",
        lambda db, library_id: db.library_files.get_uncalibrated_tagged_file_ids(library_id),
    )


@dataclass
class FakeFileStates:
    """Minimal file-state facade for pipeline integration tests."""

    untagged_counts: dict[str, int] = field(default_factory=dict)
    tagged_counts: dict[str, int] = field(default_factory=dict)
    uncalibrated_tagged_ids: dict[str, list[str]] = field(default_factory=dict)

    def count_untagged_files(self, library_id: str) -> int:
        return self.untagged_counts.get(library_id, 0)

    def get_uncalibrated_tagged_file_ids(self, library_id: str) -> list[str]:
        return list(self.uncalibrated_tagged_ids.get(library_id, []))


@dataclass
class FakeLibraryFilesOps:
    """Minimal library_files facade for pipeline integration tests."""

    file_states: FakeFileStates

    def count_untagged_files(self, library_id: str) -> int:
        return self.file_states.count_untagged_files(library_id)

    def get_uncalibrated_tagged_file_ids(self, library_id: str) -> list[str]:
        return self.file_states.get_uncalibrated_tagged_file_ids(library_id)


@dataclass
class FakeLibraryPipelineStatesOps:
    """Stateful in-memory stand-in for LibraryPipelineStatesOps."""

    state_by_library: dict[str, str]
    file_states: FakeFileStates
    noop_transitions: int = 0
    transition_log: list[tuple[str, str | None, str]] = field(default_factory=list)

    def transition_state(self, library_id: str, to_state: str) -> None:
        current_state = self.state_by_library.get(library_id)
        if current_state == to_state:
            self.noop_transitions += 1
            self.transition_log.append((library_id, current_state, to_state))
            return
        self.transition_log.append((library_id, current_state, to_state))
        self.state_by_library[library_id] = to_state

    def get_state(self, library_id: str) -> str:
        state = self.state_by_library.get(library_id)
        if state is None:
            msg = f"No pipeline state edge found for library {library_id}"
            raise ValueError(msg)
        return state.split("/", 1)[1]

    def get_libraries_in_state(self, state: str) -> list[str]:
        return [library_id for library_id, current_state in self.state_by_library.items() if current_state == state]

    def bulk_transition(self, from_state: str, to_state: str) -> int:
        count = 0
        for library_id, current_state in list(self.state_by_library.items()):
            if current_state != from_state:
                continue
            self.transition_state(library_id, to_state)
            count += 1
        return count

    def find_ml_complete_libraries(self, min_files: int) -> list[dict[str, Any]]:
        del min_files
        rows: list[dict[str, Any]] = []
        for library_id, current_state in self.state_by_library.items():
            if current_state != PIPELINE_ML_RUNNING:
                continue
            if self.file_states.count_untagged_files(library_id) != 0:
                continue
            rows.append(
                {
                    "library_id": library_id,
                    "tagged_count": self.file_states.tagged_counts.get(library_id, 0),
                },
            )
        return rows


@dataclass
class FakeLibrariesOps:
    """In-memory library document lookup."""

    libraries: dict[str, dict[str, Any]]
    state_by_library: dict[str, str]
    file_states: FakeFileStates

    def get_library(self, library_id: str) -> dict[str, Any] | None:
        library = self.libraries.get(library_id)
        if library is None:
            return None
        return dict(library)

    def find_ml_complete_libraries(self, min_files: int) -> list[dict[str, Any]]:
        del min_files
        rows: list[dict[str, Any]] = []
        for library_id, current_state in self.state_by_library.items():
            if current_state != PIPELINE_ML_RUNNING:
                continue
            if self.file_states.count_untagged_files(library_id) != 0:
                continue
            rows.append(
                {
                    "library_id": library_id,
                    "tagged_count": self.file_states.tagged_counts.get(library_id, 0),
                },
            )
        return rows


@dataclass
class FakeCalibrationStateOps:
    """Minimal calibration-state accessor."""

    states: list[dict[str, Any]] = field(default_factory=list)

    def count(self) -> int:
        return len(self.states)


class FakeDatabase:
    """Aggregate fake database matching the pipeline service's expectations."""

    def __init__(
        self,
        *,
        state_by_library: dict[str, str],
        libraries: dict[str, dict[str, Any]],
        file_states: FakeFileStates,
        calibration_states: list[dict[str, Any]] | None = None,
    ) -> None:
        self.file_states = file_states
        self.library_files = FakeLibraryFilesOps(file_states=file_states)
        self.library_pipeline_states = FakeLibraryPipelineStatesOps(
            state_by_library=dict(state_by_library),
            file_states=file_states,
        )
        self.libraries = FakeLibrariesOps(
            libraries=libraries,
            state_by_library=self.library_pipeline_states.state_by_library,
            file_states=file_states,
        )
        self.calibration_state = FakeCalibrationStateOps(states=list(calibration_states or []))


@dataclass
class FakeBackgroundTaskService:
    """Stores managed tasks so tests can complete them explicitly."""

    statuses: dict[str, dict[str, str] | None] = field(default_factory=dict)
    tasks: dict[str, Any] = field(default_factory=dict)
    cancelled: list[str] = field(default_factory=list)

    def start_task(self, task: Any) -> str:
        running_status = self.statuses.get(task.task_id)
        if running_status is not None and running_status.get("status") == "running":
            raise ValueError("task already running")
        self.tasks[task.task_id] = task
        self.statuses[task.task_id] = {"status": "running"}
        return str(task.task_id)

    def get_task_status(self, task_id: str) -> dict[str, str] | None:
        return self.statuses.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        if task_id not in self.statuses:
            return False
        self.cancelled.append(task_id)
        self.statuses[task_id] = {"status": "cancelled"}
        return True

    def complete_task(self, task_id: str) -> None:
        task = self.tasks[task_id]
        task.fn()
        self.statuses[task_id] = {"status": "complete"}
        if task.on_complete is not None:
            task.on_complete()


@dataclass
class FakeCalibrationService:
    """Tracks calibration dispatches."""

    started_count: int = 0

    def start_histogram_calibration_background(self) -> None:
        self.started_count += 1


@dataclass
class FakeTaggingService:
    """Captures apply and write dispatches."""

    pending_counts: dict[str, int] = field(default_factory=dict)
    apply_running: bool = False
    apply_started: int = 0
    writes_started: list[str] = field(default_factory=list)
    write_callbacks: dict[str, Callable[[], None] | None] = field(default_factory=dict)
    active_writes: set[str] = field(default_factory=set)
    clear_apply_progress_calls: int = 0
    _apply_result: Any = None
    _apply_error: Any = None

    def is_apply_running(self) -> bool:
        return self.apply_running

    def _clear_apply_progress(self) -> None:
        self.clear_apply_progress_calls += 1

    def _run_apply_calibration(self) -> None:
        self.apply_started += 1

    def start_write_tags_background(
        self,
        library_id: str,
        stop_event: Any,
        on_complete: Callable[[], None] | None = None,
    ) -> str:
        del stop_event
        if library_id in self.active_writes:
            raise ValueError("write already running")
        self.active_writes.add(library_id)
        self.writes_started.append(library_id)
        self.write_callbacks[library_id] = on_complete
        return f"write_tags:{library_id}"

    def get_reconcile_status(self, library_id: str) -> dict[str, int]:
        return {"pending_count": self.pending_counts.get(library_id, 0)}

    def complete_write(self, library_id: str) -> None:
        callback = self.write_callbacks.pop(library_id)
        self.active_writes.discard(library_id)
        if callback is not None:
            callback()


@dataclass
class FakeNavidromeService:
    """Tracks rescan dispatches."""

    rescan_calls: int = 0

    def trigger_rescan(self) -> bool:
        self.rescan_calls += 1
        return True


@dataclass
class PipelineHarness:
    """Convenience wrapper for the stateful pipeline collaborators."""

    db: FakeDatabase
    bts: FakeBackgroundTaskService
    calibration_svc: FakeCalibrationService
    tagging_svc: FakeTaggingService
    navidrome_svc: FakeNavidromeService
    service: LibraryPipelineService


def _run_idle_pipeline_completion(db: FakeDatabase, health_pipe: Any) -> int:
    """Call the worker helper with explicit test-harness casts for mypy."""
    return _check_idle_pipeline_completion(cast("Database", db), health_pipe)


def _make_harness(
    *,
    state_by_library: dict[str, str],
    libraries: dict[str, dict[str, Any]],
    untagged_counts: dict[str, int] | None = None,
    tagged_counts: dict[str, int] | None = None,
    uncalibrated_tagged_ids: dict[str, list[str]] | None = None,
    calibration_states: list[dict[str, Any]] | None = None,
    task_statuses: dict[str, dict[str, str] | None] | None = None,
) -> PipelineHarness:
    """Build a pipeline service with stateful fake collaborators."""
    file_states = FakeFileStates(
        untagged_counts=dict(untagged_counts or {}),
        tagged_counts=dict(tagged_counts or {}),
        uncalibrated_tagged_ids={
            library_id: list(file_ids) for library_id, file_ids in (uncalibrated_tagged_ids or {}).items()
        },
    )
    db = FakeDatabase(
        state_by_library=state_by_library,
        libraries=libraries,
        file_states=file_states,
        calibration_states=calibration_states,
    )
    bts = FakeBackgroundTaskService(statuses=dict(task_statuses or {}))
    calibration_svc = FakeCalibrationService()
    tagging_svc = FakeTaggingService()
    navidrome_svc = FakeNavidromeService()
    service = LibraryPipelineService(
        db=cast("Database", db),
        bts=cast("BackgroundTaskService", bts),
        calibration_svc=cast("CalibrationService", calibration_svc),
        tagging_svc=cast("TaggingService", tagging_svc),
        navidrome_svc=cast("NavidromeService", navidrome_svc),
    )
    return PipelineHarness(
        db=db,
        bts=bts,
        calibration_svc=calibration_svc,
        tagging_svc=tagging_svc,
        navidrome_svc=navidrome_svc,
        service=service,
    )


class TestPipelineIntegration:
    """End-to-end pipeline state coordination tests with mocked boundaries."""

    def test_full_pipeline_flow_auto_write_enabled_reaches_done(self) -> None:
        """idle→scanning→ml_running→awaiting_calibration→calibrating→applying→writing→done should complete."""
        library_id = "libraries/full-flow"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_ML_RUNNING},
            libraries={library_id: {"library_auto_write": True, "file_write_mode": "full"}},
            untagged_counts={library_id: 0},
            tagged_counts={library_id: INTERNAL_CALIBRATION_MIN_FILES + 25},
            uncalibrated_tagged_ids={library_id: ["library_files/1", "library_files/2"]},
        )
        health_pipe = MagicMock()

        completed = _run_idle_pipeline_completion(harness.db, health_pipe)
        assert completed == 1
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_AWAITING_CALIBRATION
        health_pipe.send.assert_called_once()

        harness.service.trigger_calibration()
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_CALIBRATING
        assert harness.calibration_svc.started_count == 1

        harness.service.on_calibration_complete()
        assert harness.bts.statuses[CALIBRATION_APPLY_TASK_ID] == {"status": "running"}

        harness.bts.complete_task(CALIBRATION_APPLY_TASK_ID)
        assert harness.tagging_svc.apply_started == 1
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_WRITING
        assert harness.tagging_svc.writes_started == [library_id]

        harness.tagging_svc.complete_write(library_id)
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_DONE
        assert harness.navidrome_svc.rescan_calls == 1

    def test_too_small_library_blocks_then_resumes_after_more_files(self) -> None:
        """Libraries below the calibration minimum should enter too_small, then resume once enough files exist."""
        library_id = "libraries/too-small"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_ML_RUNNING},
            libraries={library_id: {"library_auto_write": False, "file_write_mode": "full"}},
            untagged_counts={library_id: 0},
            tagged_counts={library_id: INTERNAL_CALIBRATION_MIN_FILES - 1},
        )

        _run_idle_pipeline_completion(harness.db, None)
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_TOO_SMALL

        harness.db.library_pipeline_states.transition_state(library_id, PIPELINE_SCANNING)
        harness.db.library_pipeline_states.transition_state(library_id, PIPELINE_ML_RUNNING)
        harness.db.file_states.tagged_counts[library_id] = INTERNAL_CALIBRATION_MIN_FILES + 10

        _run_idle_pipeline_completion(harness.db, None)
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_AWAITING_CALIBRATION

    def test_concurrent_worker_completion_keeps_second_transition_a_noop(self) -> None:
        """Duplicate completion checks should leave one real transition and one idempotent no-op."""
        library_id = "libraries/concurrent"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_ML_RUNNING},
            libraries={library_id: {"library_auto_write": False, "file_write_mode": "full"}},
            untagged_counts={library_id: 0},
            tagged_counts={library_id: INTERNAL_CALIBRATION_MIN_FILES + 1},
        )

        duplicate_row: list[dict[str, int | str]] = [
            {"library_id": library_id, "tagged_count": INTERNAL_CALIBRATION_MIN_FILES + 1}
        ]

        def _always_complete(min_files: int) -> list[dict[str, int | str]]:
            del min_files
            return list(duplicate_row)

        harness.db.libraries.find_ml_complete_libraries = _always_complete  # type: ignore[method-assign]

        _run_idle_pipeline_completion(harness.db, None)
        _run_idle_pipeline_completion(harness.db, None)

        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_AWAITING_CALIBRATION
        assert harness.db.library_pipeline_states.noop_transitions == 1

    def test_new_library_on_established_system_skips_calibration_generation(self) -> None:
        """Existing calibration data should shortcut awaiting_calibration directly into apply dispatch."""
        library_id = "libraries/established"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_AWAITING_CALIBRATION},
            libraries={library_id: {"library_auto_write": False, "file_write_mode": "full"}},
            calibration_states=[{"version": 1}],
        )

        harness.service.trigger_calibration()

        assert harness.calibration_svc.started_count == 0
        assert harness.bts.statuses[CALIBRATION_APPLY_TASK_ID] == {"status": "running"}

        harness.bts.complete_task(CALIBRATION_APPLY_TASK_ID)
        assert harness.tagging_svc.apply_started == 1
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_WRITE_READY

    def test_enabling_auto_write_in_write_ready_dispatches_write_immediately(self) -> None:
        """Turning on auto-write while write_ready should kick off write dispatch without another pipeline stage."""
        library_id = "libraries/reactive"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_WRITE_READY},
            libraries={library_id: {"library_auto_write": True, "file_write_mode": "full"}},
        )

        harness.service.handle_auto_write_enabled(library_id)

        assert harness.tagging_svc.writes_started == [library_id]

    def test_recover_stale_states_moves_calibrating_back_to_awaiting(self) -> None:
        """Startup recovery should return calibrating libraries to awaiting_calibration when no task is active."""
        library_id = "libraries/stale-calibrating"
        harness = _make_harness(
            state_by_library={library_id: PIPELINE_CALIBRATING},
            libraries={library_id: {"library_auto_write": False, "file_write_mode": "full"}},
            task_statuses={CALIBRATION_APPLY_TASK_ID: {"status": "running"}},
        )

        result = harness.service.recover_stale_states()

        assert result["calibrating"] == 1
        assert harness.db.library_pipeline_states.state_by_library[library_id] == PIPELINE_AWAITING_CALIBRATION
