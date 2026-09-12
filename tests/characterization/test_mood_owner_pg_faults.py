"""Real-driver mood-path fault evidence (D3D-B).

Drives the frozen public mood owner — ``LibraryTagsDb.replace_mood_tags`` and
``LibraryTagsDb.replace_mood_tags_batch`` — through the D3D-A TCP fault harness
(``tests/characterization/pg_fault_proxy.py``) against a real PostgreSQL +
pgvector database. Each test proves the driver-observable commit-phase outcome
(or the pre-commit contrast), and the production classification on the real owner
path:

* ``DROP_ACK``: the backend commits but the acknowledgement is discarded. The
  owner maps the pgcode-less ``DBAPIError`` to exactly one
  ``AMBIGUOUS_COMMIT`` with no blind retry.
* ``SEVER``: both sockets are severed mid-commit. The owner maps the pgcode-less
  connection loss to exactly one ``AMBIGUOUS_COMMIT`` with no replay.
* ``SEVER_PRE_COMMIT``: the connection is severed *before* any ``COMMIT`` is
  forwarded. That pre-commit pgcode-less infrastructure failure is
  ``INFRA_FAILURE`` and never ``AMBIGUOUS_COMMIT`` (classification contrast).

Both the batch path (``DROP_ACK``) and the single path (``SEVER`` /
``SEVER_PRE_COMMIT``) funnel through the same Tier-2 owner unit of work,
``SongTagRepository._replace_mood_batch_once`` -> ``_commit_mood_batch``
(``nomarr/persistence/database/song_tag_repo.py``): only the batch's public
entry differs, so the divergence proof does not need a separate node per route.

Readback after an ambiguous commit is a FRESH, direct session and establishes
only current database convergence/no-torn-state. It never proves operation
provenance, exactly-once publication, calibration completion, claim release, or
filesystem success. Public results are redacted: no locator, path, UUID,
generated id, marker token, SQL, SQLSTATE, row, session, constraint, or
credential appears.

The four real-driver fault nodes are ``characterization`` +
``requires_database`` and run under the ``database-tests`` CI job via the
``tests/characterization/`` collection path. The socket-only proxy-rendering
redaction node carries no database marker (it needs no live driver) and is
excluded from the ``requires_database`` matrix; it runs alongside the harness
suite's socket-only tests (no database marker).
Evidence labels: ``LOCAL_PASS`` = executed and passed against a real native
PostgreSQL + pgvector driver; ``CI_DEFERRED`` = the same nodes are wired into
``database-tests`` but were not executed on GitHub here; ``CI_PASS`` is never
claimed locally.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodAssignments,
    MoodBatchResult,
    MoodReplacementCommand,
    MoodWriteResult,
)
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database

from .pg_fault_proxy import FaultHarnessError, PgFaultMode, PgFaultProxy, redact_url

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.characterization

_MOOD_TIERS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


# ---------------------------------------------------------------------------
# Local helpers (this module owns its own minimal world; the mood suite's
# module-local ``mood_world`` fixture is not importable across test modules)
# ---------------------------------------------------------------------------


def _open_proxied_db(url: str) -> Database:
    """Open a single-connection ``Database`` pointed at the fault proxy.

    ``pool_size=1`` / ``max_overflow=0`` is deliberate: exactly one pooled
    connection can exist. That makes the pre-close fault-disarmed owner call on
    this same single-connection ``Database`` a discriminating leak proof — a
    leaked/poisoned session would block or fail it. ``pool.checkedout()==0`` is
    additionally read as a pool-hygiene check (see
    :func:`_assert_driver_pool_released`).
    """
    return Database(url=url, echo=False, pool_size=1, max_overflow=0)


def _assert_driver_pool_released(local_db: Database) -> None:
    """Non-discriminating pool-hygiene check while the proxy context is active.

    ``pool.checkedout()==0`` is NOT the leak proof. A server-severed connection
    is invalidated and returned to the pool by SQLAlchemy regardless of whether
    the session/transaction cleanup ran, so this check reads the same on a real
    leak and on clean cleanup — it is pooled-connection hygiene only. The
    genuine leak discriminator is the pre-close fault-disarmed owner call on the
    same single-connection ``Database`` (:func:`_assert_fault_disarmed`), which
    would raise/block on a leaked session. This check still runs BEFORE any
    test-side ``local_db.close()``/engine dispose and does not depend on proxy
    handler teardown. (The severed connection is discarded rather than
    re-pooled, so ``checkedin()`` is not a reliable count here either.)
    """
    pool = local_db._pg_engine.pool
    assert isinstance(pool, QueuePool), f"expected a QueuePool, got {type(pool).__name__}"
    checked_out = pool.checkedout()
    assert checked_out == 0, f"driver pool still has {checked_out} checked-out connection(s): pool hygiene failed"


def _assert_fault_disarmed(local_db: Database) -> None:
    """The genuine no-leak proof: fault-disarmed owner call on the same Database.

    With ``pool_size=1`` / ``max_overflow=0`` a leaked/poisoned session would
    block or fail this bounded follow-up. It runs before ``local_db.close()``
    and with the proxy still active (the one-shot fault is already consumed), so
    it is a driver-side, non-proxy-teardown call that actually raises on a
    leaked session — making it the primary discriminator for the no-leak claim.
    """
    version = local_db.get_version()
    assert version is None or isinstance(version, str)


def _mood_tags(engine: Engine, song_id: int) -> set[tuple[str, str]]:
    """Fresh-session read of the three mood tiers for one song."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.name, t.value FROM tags t JOIN song_tags st ON st.tag_id = t.id "
                "WHERE st.song_id = :song_id AND t.namespace = 'nom' "
                "AND t.name IN ('nom:mood-strict', 'nom:mood-regular', 'nom:mood-loose')"
            ),
            {"song_id": song_id},
        ).all()
    return {(str(row[0]), str(row[1])) for row in rows}


def _marker(engine: Engine, song_id: int) -> str | None:
    """Fresh-session read of the current calibration marker, if any."""
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT calibration_version FROM song_mood_calibration_markers WHERE song_id = :song_id"),
            {"song_id": song_id},
        ).scalar_one_or_none()
    return None if value is None else str(value)


def _assert_redacted(result: MoodBatchResult | MoodWriteResult, *secrets: str) -> None:
    """Assert no secret leaks through the public result's repr/str.

    Every fault node asserts ``proxy.errors == ()`` separately, so the harness
    error channel is always empty on the success path and redacting it here would
    be inert. Error-side redaction is therefore proven independently by
    :func:`test_proxy_error_surface_never_renders_credential` over the
    proxy's own rendered surfaces (``repr``/``str``/``redacted_backend_url``).
    """
    rendered = f"{result!r} {result!s} {result.status}"
    for secret in (*secrets, "normalized_path", "library_uuid", "song_id", "sql", "pgcode", "password"):
        assert secret not in rendered, f"secret {secret!r} leaked into {rendered!r}"


def test_proxy_error_surface_never_renders_credential() -> None:
    """A rendered harness/proxy surface must not disclose the backend password.

    Socket-only (no database). The fault nodes' error channel is always empty on
    the success path, so error-side redaction is proven here over the surfaces a
    failure message actually renders: the proxy's own ``repr``/``str`` and
    ``redacted_backend_url``, all of which route the backend URL through
    :func:`redact_url`. This exercises the harness redaction convention (not a
    hand-crafted raw exception string, which no redactor could be expected to
    rewrite after the fact).
    """
    secret = "s3cr3t-pw"
    url = f"postgresql+psycopg2://nomarr:{secret}@127.0.0.1:5432/nomarr_d3a_test"
    proxy = PgFaultProxy(url)
    rendered = f"{proxy!r} {proxy!s} {proxy.redacted_backend_url}"
    for leaked in (secret, "password", "s3cr3t"):
        assert leaked not in rendered, f"{leaked!r} leaked into proxy rendering {rendered!r}"
    # The redactor itself never renders the backend password, and preserves the
    # non-secret coordinates so the message remains debuggable.
    redacted = redact_url(url)
    assert secret not in redacted
    assert "127.0.0.1" in redacted and ":5432" in redacted
    # A harness error carrying no credential-bearing source cannot invent one.
    harness_error = FaultHarnessError("proxy listener accept failed")
    assert secret not in f"{harness_error!r} {harness_error!s}"


@pytest.fixture()
def mood_fault_world(db: Database, pg_engine: Engine) -> Iterator[dict]:
    """Isolated library with two songs addressed by semantic locators.

    Created through the public library API plus raw persistence inserts for the
    songs (the mood owner is the surface under test; the concurrently-migrating
    song upsert facade is not). Removed on teardown via the library cascade.
    """
    suffix = uuid.uuid4().hex[:10]
    name = f"MoodFaultLib-{suffix}"
    created = db.library.create_library(Library(name=name, root_path=f"/tmp/moodfault-{suffix}"))
    now = now_ms().value
    paths = [f"/tmp/moodfault-{suffix}/song-a.flac", f"/tmp/moodfault-{suffix}/song-b.flac"]
    with pg_engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, library_uuid FROM libraries WHERE name = :name"),
            {"name": name},
        ).one()
        library_id = int(row[0])
        library_uuid = str(row[1])
        song_ids: list[int] = []
        for path in paths:
            inserted = conn.execute(
                text(
                    "INSERT INTO songs (library_id, path, normalized_path, file_size, modified_time, created_at) "
                    "VALUES (:library_id, :path, :path, 1000, :mt, :ct) RETURNING id"
                ),
                {"library_id": library_id, "path": path, "mt": now, "ct": now},
            ).one()
            song_ids.append(int(inserted[0]))

    library_identity = LibraryIdentity(library_uuid=library_uuid, name=name, root_path=created.root_path)
    identities = tuple(SongIdentity(library=library_identity, normalized_path=path) for path in paths)
    try:
        yield {
            "library": created,
            "library_id": library_id,
            "song_ids": tuple(song_ids),
            "identities": identities,
        }
    finally:
        with contextlib.suppress(Exception):
            db.library.remove_library(created)


# ---------------------------------------------------------------------------
# Normal proxied control (the fault harness must be transparent when unarmed)
# ---------------------------------------------------------------------------


@pytest.mark.requires_database
def test_proxied_mood_path_normal_control(mood_fault_world: dict, pg_engine: Engine, test_db_url: str) -> None:
    """An unarmed proxy carries the owner transaction through unchanged."""
    song_id = mood_fault_world["song_ids"][0]
    identity = mood_fault_world["identities"][0]
    value = f"normal-{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex

    with PgFaultProxy(test_db_url) as proxy:
        assert proxy.started.wait(2.0)
        local_db = _open_proxied_db(proxy.build_proxied_url(test_db_url))
        try:
            result = local_db.library.tags.replace_mood_tags(
                identity, MoodAssignments(strict=(value,)), CalibrationMoodMarker.calibrated(marker)
            )
        finally:
            local_db.close()
        assert result == MoodWriteResult("UPDATED", assignment_count=1)
        assert proxy.errors == ()
        # commit_forwarded is the authoritative pre-ack signal; await it (bounded,
        # no sleeps) before reading the cumulative commit_count so the assertion
        # cannot race the relay thread that increments it.
        assert proxy.commit_forwarded.wait(10.0)
        assert proxy.commit_count == 1
        assert proxy.connections_accepted == 1
        assert proxy.wait_for_error(0.5) is None
        assert proxy.active_connection_count() == 0

    assert _mood_tags(pg_engine, song_id) == {("nom:mood-strict", value)}
    assert _marker(pg_engine, song_id) == marker
    _assert_redacted(result, value, marker, identity.normalized_path, identity.library.library_uuid)


# ---------------------------------------------------------------------------
# DROP_ACK: dropped commit acknowledgement -> one AMBIGUOUS_COMMIT, no retry
# ---------------------------------------------------------------------------


@pytest.mark.requires_database
def test_drop_ack_batch_is_single_ambiguous_commit_with_convergence_readback(
    db: Database, mood_fault_world: dict, pg_engine: Engine, test_db_url: str
) -> None:
    """The backend commits; the discarded ack yields exactly one AMBIGUOUS_COMMIT.

    R-A/R-B/R-C/R-D/R-E/R-F: one batch call, one forwarded ``COMMIT``, one
    accepted connection, typed ``AMBIGUOUS_COMMIT``, no replay, no leaked
    session, fresh-session convergence readback, fully redacted result.
    """
    song_ids = mood_fault_world["song_ids"]
    identities = mood_fault_world["identities"]
    value_a = f"dropack-a-{uuid.uuid4().hex[:8]}"
    value_b = f"dropack-b-{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex
    marker_obj = CalibrationMoodMarker.calibrated(marker)
    commands = tuple(
        MoodReplacementCommand(song=identity, assignments=MoodAssignments(strict=(value,)), marker=marker_obj)
        for identity, value in zip(identities, (value_a, value_b), strict=True)
    )

    with PgFaultProxy(test_db_url) as proxy:
        assert proxy.started.wait(2.0)
        proxy.arm(PgFaultMode.DROP_ACK)
        local_db = _open_proxied_db(proxy.build_proxied_url(test_db_url))
        try:
            result = local_db.library.tags.replace_mood_tags_batch(commands)
            # Pool hygiene ON the live driver pool while still inside the proxy
            # context and BEFORE any test-side close()/dispose. NOTE: this is NOT
            # the leak proof — a severed connection is invalidated and returned
            # regardless of cleanup, so checkedout()==0 reads the same on a real
            # leak. The genuine discriminator is the fault-disarmed follow-up
            # owner call below.
            assert result.status == "AMBIGUOUS_COMMIT"
            # Fault-phase counters read BEFORE the disarmed follow-up below opens
            # its deliberately-fresh proxy connection: one attempt, one connection.
            assert proxy.commit_count == 1
            assert proxy.connections_accepted == 1
            _assert_driver_pool_released(local_db)
            # The genuine no-leak proof: a fault-disarmed owner call on the SAME
            # single-connection Database still completes; a leaked/poisoned
            # session would block/fail. This intentionally opens a second proxy
            # connection.
            _assert_fault_disarmed(local_db)
        finally:
            local_db.close()
        assert isinstance(result, MoodBatchResult)
        assert result.status == "AMBIGUOUS_COMMIT"
        assert result.command_count == 2
        # One attempt, one commit forwarded, one connection during the fault.
        assert proxy.commit_count == 1
        assert proxy.connections_accepted == 2  # 1 faulted + 1 disarmed follow-up
        # Harness handler teardown only: the proxy severs its own sockets in fault
        # mode, so this is NOT a driver-leak proof. The genuine driver-side no-leak
        # proof is the fault-disarmed follow-up owner call above (pre-close); the
        # pool assertion above is non-discriminating hygiene.
        assert proxy.wait_for_no_active_connections(10.0)
        assert proxy.active_connection_count() == 0
        # The server really committed despite the discarded acknowledgement.
        assert proxy.backend_committed.wait(10.0)
        assert proxy.fault_applied.wait(10.0)
        assert proxy.wait_for_error(0.5) is None
    assert proxy.active_connection_count() == 0

    # Fresh-session convergence readback (current state only, never provenance).
    for song_id, value in zip(song_ids, (value_a, value_b), strict=True):
        assert _mood_tags(pg_engine, song_id) == {("nom:mood-strict", value)}
        assert _marker(pg_engine, song_id) == marker
    # Restart/recovery: a fresh unproxied owner call sees the converged state.
    replay = db.library.tags.replace_mood_tags_batch(commands)
    assert replay.status == "UNCHANGED"

    _assert_redacted(
        result,
        value_a,
        value_b,
        marker,
        identities[0].normalized_path,
        identities[0].library.library_uuid,
    )


# ---------------------------------------------------------------------------
# SEVER: commit-phase connection loss -> one AMBIGUOUS_COMMIT, no replay
# ---------------------------------------------------------------------------


@pytest.mark.requires_database
def test_sever_commit_phase_is_single_ambiguous_commit_with_no_leak(
    mood_fault_world: dict, pg_engine: Engine, test_db_url: str
) -> None:
    """A severed commit connection yields exactly one AMBIGUOUS_COMMIT.

    ``backend_committed`` is not awaited in SEVER mode (D3D-A handoff §4). The
    readback must never show a torn/partial state: tags and marker are asserted
    as a single joint outcome, reporting only current convergence, not
    provenance. The genuine no-leak proof is the pre-close fault-disarmed owner
    call on the same single-connection ``Database`` (``_assert_fault_disarmed``);
    the ``pool.checkedout()==0`` check is non-discriminating hygiene.
    """
    song_id = mood_fault_world["song_ids"][0]
    identity = mood_fault_world["identities"][0]
    value = f"sever-{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex

    with PgFaultProxy(test_db_url) as proxy:
        assert proxy.started.wait(2.0)
        proxy.arm(PgFaultMode.SEVER)
        local_db = _open_proxied_db(proxy.build_proxied_url(test_db_url))
        try:
            result = local_db.library.tags.replace_mood_tags(
                identity, MoodAssignments(strict=(value,)), CalibrationMoodMarker.calibrated(marker)
            )
            # Pool hygiene ON the live driver pool while still inside the proxy
            # context and BEFORE any test-side close()/dispose. NOTE: this is NOT
            # the leak proof — a severed connection is invalidated and returned
            # regardless of cleanup, so checkedout()==0 reads the same on a real
            # leak. The genuine discriminator is the fault-disarmed follow-up
            # owner call below.
            assert result.status == "AMBIGUOUS_COMMIT"
            # Fault-phase counters BEFORE the disarmed follow-up opens a fresh
            # proxy connection: one attempt, one connection.
            assert proxy.commit_count == 1
            assert proxy.connections_accepted == 1
            _assert_driver_pool_released(local_db)
            # The genuine no-leak proof: a fault-disarmed owner call on the SAME
            # single-connection Database still completes; a leaked/poisoned
            # session would block/fail. This intentionally opens a second proxy
            # connection.
            _assert_fault_disarmed(local_db)
        finally:
            local_db.close()
        assert result.status == "AMBIGUOUS_COMMIT"
        assert isinstance(result, MoodWriteResult)
        # One attempt, one commit forwarded, one connection during the fault.
        assert proxy.commit_count == 1
        assert proxy.connections_accepted == 2  # 1 faulted + 1 disarmed follow-up
        assert proxy.fault_applied.wait(10.0)
        # Harness handler teardown only: the proxy severs its own sockets in SEVER
        # mode, so this is NOT a driver-leak proof. The genuine driver-side
        # no-leak proof is the fault-disarmed follow-up owner call above
        # (pre-close); the pool assertion above is non-discriminating hygiene.
        assert proxy.wait_for_no_active_connections(10.0)
        assert proxy.active_connection_count() == 0
        # D3D-A §4: backend_committed is not used in SEVER mode.
        assert not proxy.backend_committed.is_set()
        # The sever traffic must not leave a harness error behind.
        assert proxy.wait_for_error(0.5) is None
        assert proxy.errors == ()
    assert proxy.active_connection_count() == 0

    # Convergence-only readback: the mood set and marker are asserted JOINTLY,
    # so a torn/partial combination (one converged, one absent) fails. Explicit
    # equality avoids hashing the (unhashable) set returned by _mood_tags.
    observed_tags = _mood_tags(pg_engine, song_id)
    observed_marker = _marker(pg_engine, song_id)
    fully_present = observed_tags == {("nom:mood-strict", value)} and observed_marker == marker
    fully_absent = observed_tags == set() and observed_marker is None
    assert fully_present or fully_absent, f"torn/partial state: tags={observed_tags!r}, marker={observed_marker!r}"
    _assert_redacted(result, value, marker, identity.normalized_path, identity.library.library_uuid)


# ---------------------------------------------------------------------------
# Pre-commit pgcode-less infrastructure failure -> INFRA_FAILURE (contrast)
# ---------------------------------------------------------------------------


@pytest.mark.requires_database
def test_pre_commit_sever_is_infra_failure_not_ambiguous(
    mood_fault_world: dict, pg_engine: Engine, test_db_url: str
) -> None:
    """A pgcode-less failure BEFORE the COMMIT is forwarded is INFRA_FAILURE.

    R-G: severing the connection on the first frontend frame means no ``COMMIT``
    is ever forwarded, so the owner must classify the pgcode-less failure as
    ``INFRA_FAILURE`` — never ``AMBIGUOUS_COMMIT`` — and leave no mutation.
    """
    song_id = mood_fault_world["song_ids"][0]
    identity = mood_fault_world["identities"][0]
    value = f"precommit-{uuid.uuid4().hex[:8]}"
    marker = uuid.uuid4().hex

    with PgFaultProxy(test_db_url) as proxy:
        assert proxy.started.wait(2.0)
        proxy.arm(PgFaultMode.SEVER_PRE_COMMIT)
        local_db = _open_proxied_db(proxy.build_proxied_url(test_db_url))
        try:
            result = local_db.library.tags.replace_mood_tags(
                identity, MoodAssignments(strict=(value,)), CalibrationMoodMarker.calibrated(marker)
            )
            # Pool hygiene only: the pre-commit pool signal is non-discriminating
            # (see _assert_driver_pool_released). The genuine leak proof is the
            # fault-disarmed owner call below.
            _assert_driver_pool_released(local_db)
            _assert_fault_disarmed(local_db)
        finally:
            local_db.close()
        assert proxy.fault_applied.wait(10.0)
        # The COMMIT was never forwarded: this is strictly a pre-commit failure.
        assert proxy.commit_count == 0
        assert not proxy.commit_forwarded.is_set()
        assert proxy.connections_accepted == 2  # 1 faulted + 1 disarmed follow-up
        # Harness handler teardown only (the proxy severed both sockets), so this
        # is not a driver-leak proof; the fault-disarmed follow-up owner call
        # above is.
        assert proxy.wait_for_no_active_connections(10.0)
        assert proxy.active_connection_count() == 0
        # The sever traffic must not leave a harness error behind.
        assert proxy.wait_for_error(0.5) is None
        assert proxy.errors == ()
    assert proxy.active_connection_count() == 0

    assert result.status == "INFRA_FAILURE"
    assert result.status != "AMBIGUOUS_COMMIT"
    # No mutation: the failure happened before any owner SQL committed.
    assert _mood_tags(pg_engine, song_id) == set()
    assert _marker(pg_engine, song_id) is None
    _assert_redacted(result, value, marker, identity.normalized_path, identity.library.library_uuid)
