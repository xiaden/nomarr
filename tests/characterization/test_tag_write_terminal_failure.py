"""Real-PostgreSQL characterization of the tag-write terminal-failure policy.

Plan: ``TASK-canonical-filesystem-access-F-tag-write-terminal-failure-policy``,
Phase 1 (spec-first, RED). These tests drive the REAL ``TaggingService``
reconciliation run against a migrated PostgreSQL database (the
``tests/characterization/conftest.py`` session fixtures) over a real ``libraries``
row rooted at ``tmp_path`` with real on-disk files. Only
``nomarr.workflows.processing.write_file_tags_wf.TagWriter`` is patched, so the
real state/claim workflow, the real reconciliation claim/count helpers and the
real pipeline ``on_write_complete`` policy execute.

Authored against ADR-051 / ``DD-tag-write-reconciliation-terminal-failure.md``
v0.8: bounded run-local retry (N=3), run-scoped exclusion, failed files left
``not_written`` with their claim released and still in the pending union, and a
partial run that does not trigger a Navidrome rescan.

Docker/testcontainers is unavailable in this authoring workspace (checked:
``docker`` absent, port 5432 closed, ``NOMARR_TEST_DATABASE_URL`` unset), so this
module cannot be executed here; it is authored against the CI ``database-tests``
harness. The environment blocker is reported honestly — unavailable
infrastructure is not PASS.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_scan_state_comp import get_pipeline_state
from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.library.reconciliation_comp import count_files_needing_reconciliation
from nomarr.helpers.constants.file_states import STATE_HYDRATED, STATE_NOT_HYDRATED, STATE_NOT_WRITTEN, STATE_WRITTEN
from nomarr.helpers.constants.pipeline_states import WRITE_NOT_WRITTEN, WRITE_STATE_FIELD
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.services.domain.tagging_svc import TaggingService, TaggingServiceConfig
from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from nomarr.persistence.db import Database

pytestmark = [pytest.mark.characterization, pytest.mark.requires_database]

_FAILING_RELATIVE = "bad.flac"
_JOIN_TIMEOUT_S = 20.0


def _recording_writer(*, attempts: list[str]) -> type:
    """Build a fake ``TagWriter`` recording every ``write_safe`` attempt.

    ``bad.flac`` always fails with a retryable structured ``write_failed``
    outcome; every other file succeeds. The returned value is duck-typed with the
    future ``SafeWriteResult`` fields (``outcome``/``fs_fact``) plus the HEAD
    ``error`` string so the same fake works before and after Phase 2.
    """

    class _RecordingWriter:
        def __init__(self, overwrite: bool = True, namespace: str = "nom") -> None:
            self.overwrite = overwrite
            self.namespace = namespace

        def write_safe(self, path, tags, library_root, expected_mtime_ms) -> SimpleNamespace:  # type: ignore[no-untyped-def]
            attempts.append(path.relative)
            if path.relative == _FAILING_RELATIVE:
                return SimpleNamespace(
                    success=False,
                    outcome="write_failed",
                    fs_fact=None,
                    new_mtime_ms=None,
                    error="Safe write failed: persistent",
                )
            return SimpleNamespace(
                success=True,
                outcome=None,
                fs_fact=None,
                new_mtime_ms=expected_mtime_ms,
                error=None,
            )

    return _RecordingWriter


def _seed_library(db: Database, tmp_path: Path, *, library_name: str) -> tuple[Library, LibraryIdentity]:
    """Create one real library and two songs, with on-disk mtime-matching files."""
    lib = db.library.create_library(Library(name=library_name, root_path=str(tmp_path), file_write_mode="full"))
    assert lib.library_uuid is not None
    identity = LibraryIdentity(library_uuid=lib.library_uuid, name=lib.name, root_path=lib.root_path)

    song_identities: list[SongIdentity] = []
    for normalized_path in ("good.flac", _FAILING_RELATIVE):
        audio_path = tmp_path / normalized_path
        audio_path.write_bytes(f"audio-{normalized_path}".encode())
        stat = audio_path.stat()
        song_identities.append(
            db.library.add_song_to_library(
                SongUpsertInput(
                    library=identity,
                    path=str(audio_path),
                    scan=SongScanUpdate(
                        normalized_path=normalized_path,
                        file_size=stat.st_size,
                        modified_time=int(stat.st_mtime * 1000),
                        duration_seconds=180.0,
                        is_valid=True,
                        scanned_at=1,
                    ),
                )
            )
        )

    # Exercise real write admission while preserving the negative write/tag
    # freshness poles used by the ADR-051 characterization.
    transition_song_state(db, song_identities, STATE_NOT_HYDRATED, STATE_HYDRATED)
    return lib, identity


def _make_service(db: Database, bts: BackgroundTaskService) -> TaggingService:
    return TaggingService(
        database=db,
        cfg=TaggingServiceConfig(
            models_dir="models",
            namespace="nom",
            version_tag_key="nom:version",
        ),
        bts=bts,
        config_service=MagicMock(),
    )


def _run_write(
    service: TaggingService,
    bts: BackgroundTaskService,
    library: Library,
    *,
    on_complete: Callable[[], None] | None = None,
) -> dict:
    """Dispatch the real run and wait for a bounded terminal state."""
    stop_event = threading.Event()
    task_id = service.start_write_tags_background(library, stop_event, on_complete=on_complete)
    thread = bts._tasks[task_id][0]
    thread.join(timeout=_JOIN_TIMEOUT_S)
    assert not thread.is_alive(), "tag-write run did not reach a terminal state within the bounded join"
    status = bts.get_task_status(task_id)
    assert status is not None
    return status


def _identities_in_state(db: Database, library: Library, state: str) -> set[SongIdentity]:
    assert library.library_uuid is not None
    identity = LibraryIdentity(library_uuid=library.library_uuid, name=library.name, root_path=library.root_path)
    return {candidate.identity for candidate in db.library.list_songs_with_state(state, library=identity)}


def _song_identity(identity: LibraryIdentity, normalized_path: str) -> SongIdentity:
    return SongIdentity(library=identity, normalized_path=normalized_path)


class TestTerminalFailureCharacterization:
    """Real-DB proofs of bounded termination, partial visibility, and rescan policy."""

    def test_persistent_failure_terminates_partial_and_leaves_failing_file_pending(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        lib, identity = _seed_library(db, tmp_path, library_name="TFTerminal")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)

            status = _run_write(service, bts, lib)

            assert status["status"] == "complete"
            result = status["result"]
            assert result is not None
            assert result.outcome == "partial"
            assert count_files_needing_reconciliation(db, lib) == 1
            assert _song_identity(identity, _FAILING_RELATIVE) in _identities_in_state(db, lib, STATE_NOT_WRITTEN)
        finally:
            db.library.remove_library(lib)

    def test_successes_are_marked_written_and_failing_file_is_not_written(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R3: successes advance to ``written``; the failing file stays ``not_written``."""
        lib, identity = _seed_library(db, tmp_path, library_name="TFR3")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)

            _run_write(service, bts, lib)

            written = _identities_in_state(db, lib, STATE_WRITTEN)
            pending = _identities_in_state(db, lib, STATE_NOT_WRITTEN)
            assert _song_identity(identity, "good.flac") in written
            assert _song_identity(identity, _FAILING_RELATIVE) not in written
            assert _song_identity(identity, _FAILING_RELATIVE) in pending
        finally:
            db.library.remove_library(lib)

    def test_claim_released_and_failing_file_still_in_pending_union(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R2: the terminal failure releases the claim but stays in the pending union."""
        lib, identity = _seed_library(db, tmp_path, library_name="TFR2")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)

            _run_write(service, bts, lib)

            failing = _song_identity(identity, _FAILING_RELATIVE)
            assert all(claim.song != failing for claim in db.app.list_claims())
            assert count_files_needing_reconciliation(db, lib) == 1
            assert failing in _identities_in_state(db, lib, STATE_NOT_WRITTEN)
        finally:
            db.library.remove_library(lib)

    def test_retryable_budget_exhausted_after_three_real_attempts(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R7: a retryable failure is attempted exactly three times in one real run."""
        lib, _identity = _seed_library(db, tmp_path, library_name="TFR7")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)

            _run_write(service, bts, lib)

            assert attempts.count(_FAILING_RELATIVE) == 3
            assert attempts.count("good.flac") == 1
        finally:
            db.library.remove_library(lib)

    def test_fresh_run_retries_failing_file_with_new_budget(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R6/R10: a second dispatch starts a fresh run-local budget for the same file."""
        lib, _identity = _seed_library(db, tmp_path, library_name="TFR6")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)

            _run_write(service, bts, lib)
            assert attempts.count(_FAILING_RELATIVE) == 3

            _run_write(service, bts, lib)
            assert attempts.count(_FAILING_RELATIVE) == 6
        finally:
            db.library.remove_library(lib)

    def test_partial_run_does_not_trigger_navidrome_rescan(
        self,
        db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """R5: a partial run leaves the axis ``not_written`` and never triggers a rescan."""
        lib, _identity = _seed_library(db, tmp_path, library_name="TFR5")
        attempts: list[str] = []
        monkeypatch.setattr(
            "nomarr.workflows.processing.write_file_tags_wf.TagWriter",
            _recording_writer(attempts=attempts),
        )
        try:
            bts = BackgroundTaskService()
            service = _make_service(db, bts)
            navidrome = MagicMock()
            pipeline = LibraryPipelineService(
                db=db,
                bts=bts,
                calibration_svc=MagicMock(),
                tagging_svc=service,
                navidrome_svc=navidrome,
            )

            def _on_complete() -> None:
                pipeline.on_write_complete(lib, remaining=count_files_needing_reconciliation(db, lib))

            status = _run_write(service, bts, lib, on_complete=_on_complete)

            assert status["status"] == "complete"
            assert status["result"].outcome == "partial"
            navidrome.trigger_rescan.assert_not_called()
            assert getattr(get_pipeline_state(db, lib), WRITE_STATE_FIELD) == WRITE_NOT_WRITTEN
        finally:
            db.library.remove_library(lib)
