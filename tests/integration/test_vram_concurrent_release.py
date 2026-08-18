"""Concurrent VRAM promise release integration test.

Verifies the atomic no-stale-promise semantics of ``AppDb.release_vram``
when multiple release attempts target the same (worker_id, model_path)
pair at the same time.

The absorbed VRAM-promises adapter's ``release`` had a read-modify-write
race: it listed all promises, matched the first row for the pair, and
deleted it by id — a concurrent release could interleave and leave a
stale promise behind. ``AppDb.release_vram`` instead deletes every
matching row in a single transaction guarded by ``SELECT ... FOR UPDATE``.

NOTE ON CONCURRENCY AND LOCKING: the four release attempts are launched
simultaneously through a barrier, but their database work is serialized
by (a) SQLAlchemy's session concurrency guard — a single ``Session``
cannot run concurrent operations, so the session is protected by a lock —
and (b) SQLite itself, which serializes DML at the file level and ignores
``SELECT ... FOR UPDATE`` (no-op). This test therefore proves the
*no-stale semantics*: after N concurrent release attempts no promise rows
remain for the pair and no exception escapes. True row-lock contention
proof requires PostgreSQL (Docker) and is deferred.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.api.application import AppDb
from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

WORKER_ID = "worker:concurrent"
MODEL_PATH = "/models/concurrent.onnx"
OTHER_WORKER = "worker:other"
OTHER_MODEL = "/models/other.onnx"

_N_THREADS = 4


def _make_app_db(session: Session) -> AppDb:
    """Wire an ``AppDb`` over the integration SQLite session.

    Only the app repository is real; the other repositories are mocked
    because this test exercises the VRAM promise path only.
    """
    return AppDb(
        session=session,
        app_repo=AppRepository(session),
        library_repo=MagicMock(spec=LibraryRepository),
        song_state_repo=MagicMock(spec=SongStateRepository),
        pipeline_repo=MagicMock(spec=PipelineRepository),
    )


@pytest.mark.integration
def test_concurrent_release_leaves_no_stale_promises(pg_session) -> None:
    """Concurrent release_vram attempts leave zero rows for the pair."""
    db = _make_app_db(pg_session)

    # Two promises for the same worker+model — the old list-then-break
    # release() would only ever delete the first match it found, leaving
    # the second row stale.
    db.promise_vram(
        worker_id=WORKER_ID,
        pid=1,
        model_path=MODEL_PATH,
        promised_mb=512.0,
        total_mb=8000.0,
        used_mb=1000.0,
    )
    db.promise_vram(
        worker_id=WORKER_ID,
        pid=2,
        model_path=MODEL_PATH,
        promised_mb=256.0,
        total_mb=8000.0,
        used_mb=1000.0,
    )
    # A non-matching promise that must survive the release storm.
    db.promise_vram(
        worker_id=OTHER_WORKER,
        pid=3,
        model_path=OTHER_MODEL,
        promised_mb=128.0,
        total_mb=8000.0,
        used_mb=1000.0,
    )

    barrier = Barrier(_N_THREADS)
    # SQLAlchemy forbids concurrent operations on a single Session, so the
    # session work is serialized; threads still attempt simultaneously.
    session_lock = threading.Lock()

    def _release() -> None:
        barrier.wait()
        with session_lock:
            db.release_vram(worker_id=WORKER_ID, model_path=MODEL_PATH)

    with ThreadPoolExecutor(max_workers=_N_THREADS) as pool:
        futures = [pool.submit(_release) for _ in range(_N_THREADS)]
        # Any exception raised inside a worker thread propagates here.
        for future in futures:
            future.result(timeout=30)

    remaining = db.list_vram_promises()

    stale = [p for p in remaining if p["worker_id"] == WORKER_ID and p["model_path"] == MODEL_PATH]
    assert stale == [], f"stale promises survived concurrent release: {stale}"

    survivors = [p for p in remaining if p["worker_id"] == OTHER_WORKER and p["model_path"] == OTHER_MODEL]
    assert len(survivors) == 1, f"non-matching promise was wrongly released: {survivors}"
