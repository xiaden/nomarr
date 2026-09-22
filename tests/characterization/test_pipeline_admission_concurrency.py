"""Real PostgreSQL evidence for library-scoped pipeline admission serialization."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import LibraryOperationConflict
from nomarr.helpers.time_helper import internal_ms
from nomarr.persistence.db import Database


def _library_id(pg_engine, library: Library) -> int:
    with pg_engine.connect() as connection:
        return int(
            connection.execute(text("SELECT id FROM libraries WHERE name = :name"), {"name": library.name}).scalar_one()
        )


def _wait_until_blocked(pg_engine, pid_holder: dict[str, int], blocker_pid: int) -> None:
    deadline = internal_ms().value + 20_000
    while internal_ms().value < deadline:
        pid = pid_holder.get("pid")
        if pid is not None:
            with pg_engine.connect() as connection:
                blockers = connection.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()
            if blocker_pid in set(blockers or ()):
                return
        time.sleep(0.02)
    pytest.fail("admission backend was not observed waiting on the parent library row")


def _start_admission(
    test_db_url: str,
    library: Library,
    operation: str,
    result: dict[str, Any],
    errors: list[BaseException],
) -> threading.Thread:
    def run() -> None:
        local_db = Database(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
        try:
            result["pid"] = int(local_db._scoped.execute(text("SELECT pg_backend_pid()")).scalar_one())
            if operation == "scan":
                result["state"] = local_db.library.admit_scan(library)
            else:
                result["state"] = local_db.library.admit_tag_write(library)
        except LibraryOperationConflict as exc:
            result["conflict"] = exc
        except BaseException as exc:  # pragma: no cover - surfaced by the assertion below
            errors.append(exc)
        finally:
            local_db.close()

    thread = threading.Thread(target=run)
    thread.start()
    return thread


@pytest.mark.characterization
@pytest.mark.requires_database
class TestFirstUsePipelineAdmission:
    def _new_library(self, db: Database) -> Library:
        suffix = uuid.uuid4().hex[:10]
        return db.library.create_library(Library(name=f"Admission-{suffix}", root_path=f"/tmp/admission-{suffix}"))

    def test_first_use_scan_and_write_share_parent_lock(self, db: Database, pg_engine, test_db_url: str) -> None:
        library = self._new_library(db)
        library_id = _library_id(pg_engine, library)
        with pg_engine.begin() as connection:
            connection.execute(text("DELETE FROM pipeline_states WHERE library_id = :id"), {"id": library_id})

        blocker = pg_engine.connect()
        try:
            blocker.execute(text("SELECT id FROM libraries WHERE id = :id FOR UPDATE"), {"id": library_id})
            blocker_pid = int(blocker.execute(text("SELECT pg_backend_pid()")).scalar_one())
            scan_result: dict[str, Any] = {}
            write_result: dict[str, Any] = {}
            errors: list[BaseException] = []
            scan_thread = _start_admission(test_db_url, library, "scan", scan_result, errors)
            _wait_until_blocked(pg_engine, scan_result, blocker_pid)
            write_thread = _start_admission(test_db_url, library, "write", write_result, errors)
            time.sleep(0.1)
            blocker.commit()
            scan_thread.join(timeout=30)
            write_thread.join(timeout=30)
            assert not scan_thread.is_alive() and not write_thread.is_alive()
            assert not errors, errors
            assert ("state" in scan_result) ^ ("state" in write_result)
            conflict = write_result.get("conflict") or scan_result.get("conflict")
            assert isinstance(conflict, LibraryOperationConflict)
        finally:
            blocker.close()
            db.library.remove_library(library)

    def test_existing_pipeline_rows_preserve_opposite_axis(self, db: Database, pg_engine) -> None:
        library = self._new_library(db)
        try:
            db.library.set_pipeline_axis(library, "scan_state", "scanned")
            admitted = db.library.admit_tag_write(library)
            assert admitted.scan_state == "scanned"
            assert admitted.tag_write_state == "writing"
        finally:
            db.library.remove_library(library)

    def test_first_use_write_and_write_have_one_winner(self, db: Database, pg_engine, test_db_url: str) -> None:
        library = self._new_library(db)
        library_id = _library_id(pg_engine, library)
        with pg_engine.begin() as connection:
            connection.execute(text("DELETE FROM pipeline_states WHERE library_id = :id"), {"id": library_id})

        blocker = pg_engine.connect()
        try:
            blocker.execute(text("SELECT id FROM libraries WHERE id = :id FOR UPDATE"), {"id": library_id})
            blocker_pid = int(blocker.execute(text("SELECT pg_backend_pid()")).scalar_one())
            first: dict[str, Any] = {}
            second: dict[str, Any] = {}
            errors: list[BaseException] = []
            first_thread = _start_admission(test_db_url, library, "write", first, errors)
            _wait_until_blocked(pg_engine, first, blocker_pid)
            second_thread = _start_admission(test_db_url, library, "write", second, errors)
            time.sleep(0.1)
            blocker.commit()
            first_thread.join(timeout=30)
            second_thread.join(timeout=30)
            assert not first_thread.is_alive() and not second_thread.is_alive()
            assert not errors, errors
            assert ("state" in first) ^ ("state" in second)
            conflict = second.get("conflict") or first.get("conflict")
            assert isinstance(conflict, LibraryOperationConflict)
        finally:
            blocker.close()
            db.library.remove_library(library)
