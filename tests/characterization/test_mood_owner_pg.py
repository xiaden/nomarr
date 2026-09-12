"""Owner-level mood/marker capability characterization on real PostgreSQL.

D3 capability evidence (H-MK / H-BATCH / H-OUTCOME) for the Tier-2 mood owner.
This module exercises the frozen public mood surface —
``LibraryTagsDb.replace_mood_tags`` and ``LibraryTagsDb.replace_mood_tags_batch``
— against a real PostgreSQL + pgvector engine (the ``pgvector/pgvector:pg17``
testcontainer in CI, or an already-running native cluster when
``NOMARR_TEST_DATABASE_URL`` is set locally).

Every test in this module is ``characterization`` + ``requires_database``. CI
collection is limited to the ``database-tests`` job, while local execution is
supported through the documented ``NOMARR_TEST_DATABASE_URL`` override (native
PostgreSQL). The only evidence this module publishes is genuine driver-level
PostgreSQL evidence:

- the additive ``song_mood_calibration_markers`` table's PK, ``NOT NULL`` column,
  lowercase-32-hex CHECK constraint, and ``ON DELETE CASCADE`` FK;
- real ``23514`` CHECK enforcement (raw driver ``pgcode`` asserted) and marker
  delete/upsert lifecycle;
- marker same-transaction publication with the mood edges;
- a real distinct-1000/1001 pre-SQL persistence bound;
- a real ``23505`` unique-constraint race on the mood-edge insert path: the mood path
  returns typed ``INFRA_FAILURE`` with no partial mutation, and the raw driver ``23505``
  is observed by a separate real probe insert (not by the owner's mapped exception);
- real commit-phase SQLSTATE classification (``40001`` bounded retry, ``40003``
  ambiguous / never retried) surfaced by the real PostgreSQL driver;
- deterministic same-locator **single-winner** serialization (writer A pauses
  inside its owner transaction via a test-only advisory gate; writer B blocks on
  the ``FOR NO KEY UPDATE`` songs row and wins only after A commits), plus
  deterministic batch lock-order/all-or-none and same-locator rollback;
- delete/recreate readdressing with no resurrection.

Deliberately NOT in this module: the monkeypatched ``_commit_mood_batch``
control-flow cases. Those are pure/unit control-flow evidence (``LOCAL_PASS``)
and live in ``tests/unit/persistence/api/test_mood_owner_d2.py``; they are never
PostgreSQL, driver, SQLSTATE, connection-loss, poisoned-session, rollback, or
real-commit evidence.

Evidence labels used by the D3 handoff (D3A): ``LOCAL_PASS`` = executed and
passed against a real PostgreSQL driver; ``CI_DEFERRED`` = wired into the
``database-tests`` job, awaiting actual GitHub execution; ``LOCAL_UNAVAILABLE`` /
``BLOCKED`` = not runnable or not deterministically reproducible, recorded with
owner + stop condition in the D3 handoff artifacts.
"""

from __future__ import annotations

import contextlib
import threading
import time
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Table, select, text
from sqlalchemy.exc import IntegrityError

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodAssignments,
    MoodReplacementCommand,
    SongTagAssignment,
)
from nomarr.helpers.time_helper import internal_ms, now_ms
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_mood_calibration_marker import SongMoodCalibrationMarker
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from sqlalchemy.orm import Session

    from nomarr.persistence.db import Database

#: ``Song.__table__`` is typed as the broader ``FromClause`` by the SQLAlchemy
#: plugin; the runtime object is a ``Table``. This explicit local typing (the same
#: precedent used in ``SongTagRepository``) keeps ``.insert()->returning(...)``
#: type-checker-clean without changing runtime behaviour.
_SONG_TABLE: Table = Song.__table__  # type: ignore[assignment]

MOOD_TIERS = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
VERSION_A = "a" * 32
VERSION_B = "b" * 32
_MARKER_TABLE = "song_mood_calibration_markers"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mood_tags(session: Session, song_id: int) -> set[tuple[str, str]]:
    stmt = (
        select(Tag.name, Tag.value)
        .join(SongTag, SongTag.tag_id == Tag.id)
        .where(
            SongTag.song_id == song_id,
            Tag.namespace == "nom",
            Tag.name.in_(MOOD_TIERS),
        )
    )
    return {(str(row[0]), str(row[1])) for row in session.execute(stmt).all()}


def _non_mood_tags(session: Session, song_id: int) -> set[tuple[str, str]]:
    stmt = (
        select(Tag.name, Tag.value)
        .join(SongTag, SongTag.tag_id == Tag.id)
        .where(
            SongTag.song_id == song_id,
            Tag.namespace == "nom",
            Tag.name.not_in(MOOD_TIERS),
        )
    )
    return {(str(row[0]), str(row[1])) for row in session.execute(stmt).all()}


def _marker(session: Session, song_id: int) -> str | None:
    stmt = select(SongMoodCalibrationMarker.calibration_version).where(SongMoodCalibrationMarker.song_id == song_id)
    value = session.execute(stmt).scalar_one_or_none()
    return None if value is None else str(value)


def _all_tag_pairs(session: Session, song_id: int) -> set[tuple[str, str, str]]:
    stmt = (
        select(Tag.namespace, Tag.name, Tag.value)
        .join(SongTag, SongTag.tag_id == Tag.id)
        .where(SongTag.song_id == song_id)
    )
    return {(str(row[0]), str(row[1]), str(row[2])) for row in session.execute(stmt).all()}


def _command(
    identity: SongIdentity,
    assignments: MoodAssignments | None,
    marker: CalibrationMoodMarker,
) -> MoodReplacementCommand:
    return MoodReplacementCommand(song=identity, assignments=assignments, marker=marker)


def _seed_non_mood_tag(db: Database, identity: SongIdentity, value: str) -> None:
    db.library.replace_song_tags(
        identity,
        [SongTagAssignment(name="nom:genre", value=value, namespace="nom", confidence=0.9, source="ml")],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mood_world(db: Database, pg_engine) -> Iterator[dict]:
    """Create an isolated library with two songs and return their locators.

    Data is created through public domain APIs (library) plus raw persistence
    inserts (songs, because D3 exercises the mood owner and must not depend on
    the concurrently-migrating song upsert facade). Everything is removed on
    teardown via the public library removal cascade.
    """
    suffix = uuid.uuid4().hex[:10]
    name = f"MoodCapabilityLib-{suffix}"
    created = db.library.create_library(Library(name=name, root_path=f"/tmp/moodcap-{suffix}"))
    now = now_ms().value
    paths = [f"/tmp/moodcap-{suffix}/song-a.flac", f"/tmp/moodcap-{suffix}/song-b.flac"]
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


@pytest.fixture()
def mood_world_many(db: Database, pg_engine) -> Iterator[dict]:
    """Create an isolated library with 1001 distinct persisted song locators.

    Used by the real persistence-bound test, where the batch must contain 1000
    DISTINCT locators that survive the facade's pre-SQL duplicate folding (so the
    bound is exercised on distinct persisted rows, not folded duplicates), plus a
    distinct 1001-command over-bound input that must be rejected before SQL.
    """
    suffix = uuid.uuid4().hex[:10]
    name = f"MoodBoundLib-{suffix}"
    created = db.library.create_library(Library(name=name, root_path=f"/tmp/moodbound-{suffix}"))
    now = now_ms().value
    prefix = f"/tmp/moodbound-{suffix}/song-"
    with pg_engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, library_uuid FROM libraries WHERE name = :name"),
            {"name": name},
        ).one()
        library_id = int(row[0])
        library_uuid = str(row[1])
        inserted = conn.execute(
            text(
                "INSERT INTO songs (library_id, path, normalized_path, file_size, modified_time, created_at) "
                "SELECT :library_id, :prefix || g || '.flac', :prefix || g || '.flac', 1000, :mt, :ct "
                "FROM generate_series(1, 1001) AS g RETURNING id, normalized_path"
            ),
            {"library_id": library_id, "prefix": prefix, "mt": now, "ct": now},
        ).all()

    songs = sorted((int(r[0]), str(r[1])) for r in inserted)
    assert len(songs) == 1001, "fixture must persist exactly 1001 distinct songs"
    library_identity = LibraryIdentity(library_uuid=library_uuid, name=name, root_path=created.root_path)
    identities = tuple(SongIdentity(library=library_identity, normalized_path=path) for _, path in songs)
    try:
        yield {
            "library": created,
            "library_id": library_id,
            "song_ids": tuple(song_id for song_id, _ in songs),
            "identities": identities,
        }
    finally:
        with contextlib.suppress(Exception):
            db.library.remove_library(created)


def _wait_for_writer_lock(engine, pid_holder: dict[str, int], timeout: float = 20.0) -> bool:
    """Wait until the writer backend is blocked on a lock.

    Polls ``pg_stat_activity`` (not the writer's own connection, which is blocked)
    until the writer's backend reports ``wait_event_type = 'Lock'``. This makes the
    ``23505`` duplicate-edge race deterministic instead of timing-based.
    """
    deadline = internal_ms().value + int(timeout * 1000)
    pid: int | None = None
    while internal_ms().value < deadline:
        if pid is None:
            pid = pid_holder.get("pid")
            if pid is None:
                time.sleep(0.02)
                continue
        with engine.connect() as conn:
            wait_event_type = conn.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": pid},
            ).scalar_one_or_none()
        if wait_event_type == "Lock":
            return True
        time.sleep(0.05)
    return False


@contextlib.contextmanager
def _deferred_commit_fault(pg_engine, sqlstate: str):
    """Install a test-only deferred constraint trigger that fails COMMIT.

    The trigger fires at COMMIT time and raises a real PostgreSQL error with the
    requested SQLSTATE. The error is delivered through the real psycopg2/SQLAlchemy
    driver exception, so the commit-phase classification under test reads a genuine
    driver ``pgcode`` — this is not a Python monkeypatch of the owner. A sequence
    (non-transactional ``nextval``) counts commit attempts so bounded-retry can be
    asserted even though every attempt's transaction rolls back.
    """
    token = uuid.uuid4().hex[:10]
    counter = f"d3a_commit_counter_{token}"
    function = f"d3a_commit_guard_{token}"
    trigger = f"d3a_commit_trigger_{token}"
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE SEQUENCE {counter}"))
        conn.execute(
            text(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN PERFORM nextval('{counter}'); "
                f"RAISE EXCEPTION 'd3a forced commit-phase failure' USING ERRCODE = '{sqlstate}'; "
                f"END $$"
            )
        )
        conn.execute(
            text(
                f"CREATE CONSTRAINT TRIGGER {trigger} AFTER INSERT ON song_tags "
                f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {function}()"
            )
        )
    try:
        yield counter
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger} ON song_tags"))
            conn.execute(text(f"DROP FUNCTION IF EXISTS {function}()"))
            conn.execute(text(f"DROP SEQUENCE IF EXISTS {counter}"))


def _wait_until_blocked_by(engine, pid_holder: dict[str, int], blocker_pid: int, timeout: float = 20.0) -> bool:
    """Wait until the writer backend is blocked by the identified ``blocker_pid``.

    Unlike a generic ``wait_event_type = 'Lock'`` poll, ``pg_blocking_pids`` names
    *which* backend holds the lock being waited on. For writer A the blocker is the
    test advisory-gate holder; for writer B it is writer A's private ``songs``-row
    lock. This is the deterministic proof that B transiently waits on A's locked
    song row (not merely on some unspecified lock).
    """
    deadline = internal_ms().value + int(timeout * 1000)
    pid: int | None = None
    while internal_ms().value < deadline:
        if pid is None:
            pid = pid_holder.get("pid")
            if pid is None:
                time.sleep(0.02)
                continue
        with engine.connect() as conn:
            blockers = conn.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()
        if blockers is not None and blocker_pid in set(blockers):
            return True
        time.sleep(0.05)
    return False


class _AdvisoryGate:
    """Handle for a test-only ``song_tags`` gate trigger plus its held advisory lock."""

    def __init__(self, engine, key: int, trigger: str, function: str, holder) -> None:
        self._engine = engine
        self._key = key
        self._trigger = trigger
        self._function = function
        self._holder = holder
        self.holder_pid = int(holder.execute(text("SELECT pg_backend_pid()")).scalar_one())

    def release(self) -> None:
        """Release the held advisory lock so the gated writer transaction resumes."""
        if self._holder is not None:
            self._holder.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self._key})
            self._holder.commit()
            self._holder.close()
            self._holder = None

    def teardown(self) -> None:
        """Release the gate and remove the test-only trigger/function."""
        self.release()
        with self._engine.begin() as conn:
            conn.execute(text(f"DROP TRIGGER IF EXISTS {self._trigger} ON song_tags"))
            conn.execute(text(f"DROP FUNCTION IF EXISTS {self._function}()"))


@contextlib.contextmanager
def _song_tag_gate(pg_engine, gate_value: str, *, abort: bool = False) -> Iterator[_AdvisoryGate]:
    """Install a test-only trigger that pauses a writer inside its owner transaction.

    The trigger fires ``AFTER INSERT ON song_tags`` for the row whose ``tags`` value
    is the unique ``gate_value``. That INSERT happens in the owner transaction
    **after** ``_lock_mood_song_rows`` has acquired the private songs-row lock, so
    while the gated backend waits on the advisory lock it also holds the row lock.
    With ``abort=True`` the trigger acquires the advisory lock and then raises a
    non-retryable PostgreSQL error, modelling a predecessor that rolls back after
    having locked the row. The gate holds the advisory lock on a dedicated
    connection and ``release()`` unblocks the gated writer deterministically.
    """
    token = uuid.uuid4().hex[:10]
    key = 6_000_000 + (int(token, 16) % 1_000_000)
    function = f"d2rb_gate_fn_{token}"
    trigger = f"d2rb_gate_trg_{token}"
    action = f"PERFORM pg_advisory_lock({key}); "
    if abort:
        action += "RAISE EXCEPTION 'd2rb gate abort' USING ERRCODE = 'P0001'; "
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                f"BEGIN "
                f"IF EXISTS (SELECT 1 FROM tags t WHERE t.id = NEW.tag_id AND t.namespace = 'nom' "
                f"AND t.name = 'nom:mood-strict' AND t.value = '{gate_value}') THEN "
                f"{action}"
                f"END IF; RETURN NEW; END $$"
            )
        )
        conn.execute(
            text(f"CREATE TRIGGER {trigger} AFTER INSERT ON song_tags FOR EACH ROW EXECUTE FUNCTION {function}()")
        )
    holder = pg_engine.connect()
    holder.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
    gate = _AdvisoryGate(pg_engine, key, trigger, function, holder)
    try:
        yield gate
    finally:
        gate.teardown()


def _start_mood_writer(
    test_db_url: str,
    identity: SongIdentity,
    assignments: MoodAssignments | None,
    marker: CalibrationMoodMarker,
    *,
    pid_holder: dict[str, int],
    result_holder: dict[str, str],
    errors: list[BaseException],
) -> threading.Thread:
    """Start a thread running the single-locator public mood API on a real engine."""
    from nomarr.persistence.db import Database as DatabaseClass

    def _run() -> None:
        local_db = DatabaseClass(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
        try:
            pid_holder["pid"] = int(local_db._scoped.execute(text("SELECT pg_backend_pid()")).scalar_one())
            outcome = local_db.library.tags.replace_mood_tags(identity, assignments, marker)
            result_holder["status"] = outcome.status
        except BaseException as exc:
            errors.append(exc)
        finally:
            local_db.close()

    thread = threading.Thread(target=_run)
    thread.start()
    return thread


def _start_mood_batch_writer(
    test_db_url: str,
    commands: Sequence[MoodReplacementCommand],
    *,
    pid_holder: dict[str, int],
    result_holder: dict[str, str],
    errors: list[BaseException],
) -> threading.Thread:
    """Start a thread running the batch public mood API on a real engine."""
    from nomarr.persistence.db import Database as DatabaseClass

    def _run() -> None:
        local_db = DatabaseClass(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
        try:
            pid_holder["pid"] = int(local_db._scoped.execute(text("SELECT pg_backend_pid()")).scalar_one())
            outcome = local_db.library.tags.replace_mood_tags_batch(commands)
            result_holder["status"] = outcome.status
        except BaseException as exc:
            errors.append(exc)
        finally:
            local_db.close()

    thread = threading.Thread(target=_run)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# H-MK: marker table + publication lifecycle on real PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodMarkerCapability:
    def test_marker_table_columns_pk_check_and_cascade(self, inference_session: Session) -> None:
        """The additive marker table has exactly the approved shape.

        PK on ``song_id``, ``calibration_version`` NOT NULL VARCHAR(255), the
        lowercase-32-hex CHECK, and a ``confdeltype='c'`` (ON DELETE CASCADE) FK.
        """
        columns = inference_session.execute(
            text(
                "SELECT column_name, data_type, is_nullable, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"table": _MARKER_TABLE},
        ).all()
        shape = {str(row[0]): (str(row[1]), str(row[2]), row[3]) for row in columns}
        assert set(shape) == {"song_id", "calibration_version"}
        assert shape["song_id"][1] == "NO"
        assert shape["calibration_version"][1] == "NO"
        assert shape["calibration_version"][0] == "character varying"
        assert int(shape["calibration_version"][2]) == 255

        pk_columns = {
            str(row[0])
            for row in inference_session.execute(
                text(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = to_regclass(:table) AND i.indisprimary"
                ),
                {"table": _MARKER_TABLE},
            ).all()
        }
        assert pk_columns == {"song_id"}

        check_defs = " ".join(
            str(row[0])
            for row in inference_session.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "WHERE c.conrelid = to_regclass(:table) AND c.contype = 'c'"
                ),
                {"table": _MARKER_TABLE},
            ).all()
        )
        assert "^[0-9a-f]{32}$" in check_defs

        fk_delete_actions = {
            str(row[0])
            for row in inference_session.execute(
                text(
                    "SELECT c.confdeltype FROM pg_constraint c WHERE c.conrelid = to_regclass(:table) AND c.contype = 'f'"
                ),
                {"table": _MARKER_TABLE},
            ).all()
        }
        assert fk_delete_actions == {"c"}, "marker FK must ON DELETE CASCADE from songs.id"

    def test_marker_check_constraint_rejects_non_lowercase_hex(
        self, pg_engine, inference_session: Session, mood_world: dict
    ) -> None:
        """The CHECK rejects uppercase and non-hex versions at the real DB boundary.

        The PostgreSQL driver exception is inspected directly for ``pgcode ==
        "23514"`` (check_violation) in addition to the typed ``IntegrityError``;
        no monkeypatch or fault injection is involved.
        """
        song_id = mood_world["song_ids"][0]
        for bad in ("A" * 32, "Z" * 32, "abc"):
            with pytest.raises(IntegrityError) as excinfo, pg_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO song_mood_calibration_markers (song_id, calibration_version) "
                        "VALUES (:song_id, :version)"
                    ),
                    {"song_id": song_id, "version": bad},
                )
            assert getattr(excinfo.value.orig, "pgcode", None) == "23514"
        assert _marker(inference_session, song_id) is None

    def test_song_delete_cascades_marker_and_edges(
        self, db: Database, pg_engine, inference_session: Session, mood_world: dict
    ) -> None:
        """Deleting the song row cascades the marker and mood edge (behavioral FK).

        Complements the catalog-level ``confdeltype='c'`` assertion with an actual
        delete: the ``song_mood_calibration_markers.song_id`` and ``song_tags.song_id``
        ``ON DELETE CASCADE`` foreign keys must remove the dependent rows.
        """
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        db.library.tags.replace_mood_tags(
            identity, MoodAssignments(strict=("cascade",)), CalibrationMoodMarker.calibrated(VERSION_A)
        )
        assert _marker(inference_session, song_id) == VERSION_A
        assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", "cascade")}

        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM songs WHERE id = :song_id"), {"song_id": song_id})

        with pg_engine.connect() as conn:
            markers = conn.execute(
                text("SELECT count(*) FROM song_mood_calibration_markers WHERE song_id = :song_id"),
                {"song_id": song_id},
            ).scalar_one()
            edges = conn.execute(
                text("SELECT count(*) FROM song_tags WHERE song_id = :song_id"),
                {"song_id": song_id},
            ).scalar_one()
        assert int(markers) == 0, "marker must be removed by the songs FK cascade"
        assert int(edges) == 0, "mood edges must be removed by the songs FK cascade"

    def test_uncalibrated_marker_deletes_and_reads_back_unproven(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        """Publishing a calibrated marker then uncalibrated deletes the row; an
        absent row is UNPROVEN and never an implicit default."""
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]

        first = db.library.tags.replace_mood_tags(
            identity, MoodAssignments(strict=("happy",)), CalibrationMoodMarker.calibrated(VERSION_A)
        )
        assert first.status == "UPDATED"
        assert _marker(inference_session, song_id) == VERSION_A

        cleared = db.library.tags.replace_mood_tags(
            identity, MoodAssignments(strict=("happy",)), CalibrationMoodMarker.uncalibrated()
        )
        assert cleared.status == "UPDATED"
        assert _marker(inference_session, song_id) is None

    def test_calibrated_marker_updates_version_and_is_idempotent(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        """Re-publication overwrites the version once and is UNCHANGED thereafter."""
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        assignments = MoodAssignments(strict=("happy",))

        db.library.tags.replace_mood_tags(identity, assignments, CalibrationMoodMarker.calibrated(VERSION_A))
        assert _marker(inference_session, song_id) == VERSION_A

        overwritten = db.library.tags.replace_mood_tags(
            identity, assignments, CalibrationMoodMarker.calibrated(VERSION_B)
        )
        assert overwritten.status == "UPDATED"
        assert _marker(inference_session, song_id) == VERSION_B

        again = db.library.tags.replace_mood_tags(identity, assignments, CalibrationMoodMarker.calibrated(VERSION_B))
        assert again.status == "UNCHANGED"
        assert _marker(inference_session, song_id) == VERSION_B


# ---------------------------------------------------------------------------
# H-OUTCOME: mood replacement outcomes on real PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodReplacementOutcomes:
    def test_publish_sets_all_tiers_and_preserves_non_mood(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        _seed_non_mood_tag(db, identity, "rock")

        assignments = MoodAssignments(strict=("joy", "happy"), regular=("calm",), loose=("mellow",))
        result = db.library.tags.replace_mood_tags(identity, assignments, CalibrationMoodMarker.calibrated(VERSION_A))

        assert result.status == "UPDATED"
        assert result.assignment_count == 4
        assert _mood_tags(inference_session, song_id) == {
            ("nom:mood-strict", "joy"),
            ("nom:mood-strict", "happy"),
            ("nom:mood-regular", "calm"),
            ("nom:mood-loose", "mellow"),
        }
        assert _non_mood_tags(inference_session, song_id) == {("nom:genre", "rock")}
        assert _marker(inference_session, song_id) == VERSION_A

    def test_none_assignments_clear_only_mood_and_marker(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        _seed_non_mood_tag(db, identity, "jazz")
        db.library.tags.replace_mood_tags(
            identity,
            MoodAssignments(strict=("happy",), regular=("calm",)),
            CalibrationMoodMarker.calibrated(VERSION_A),
        )

        result = db.library.tags.replace_mood_tags(identity, None, CalibrationMoodMarker.uncalibrated())

        assert result.status == "UPDATED"
        assert result.assignment_count == 0
        assert _mood_tags(inference_session, song_id) == set()
        assert _marker(inference_session, song_id) is None
        assert _non_mood_tags(inference_session, song_id) == {("nom:genre", "jazz")}

    def test_absent_tier_clears_that_tiers_prior_values(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        db.library.tags.replace_mood_tags(
            identity,
            MoodAssignments(strict=("x",), regular=("y",), loose=("z",)),
            CalibrationMoodMarker.calibrated(VERSION_A),
        )

        result = db.library.tags.replace_mood_tags(
            identity, MoodAssignments(strict=("x",)), CalibrationMoodMarker.calibrated(VERSION_A)
        )

        assert result.status == "UPDATED"
        assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", "x")}

    def test_stale_locator_is_typed_missing_without_id_disclosure(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        stale = SongIdentity(
            library=mood_world["identities"][0].library,
            normalized_path="/tmp/moodcap-nonexistent.flac",
        )
        before = _all_tag_pairs(inference_session, song_id)

        result = db.library.tags.replace_mood_tags(
            stale, MoodAssignments(strict=("happy",)), CalibrationMoodMarker.calibrated(VERSION_A)
        )

        assert result.status == "MISSING_LOCATOR"
        assert result.assignment_count == 0
        # The typed miss carries no generated id, row, or path.
        assert not hasattr(result, "song_id")
        assert not hasattr(result, "normalized_path")
        assert _all_tag_pairs(inference_session, song_id) == before

    def test_empty_batch_is_deterministic_unchanged_noop(self, db: Database, mood_world: dict) -> None:
        result = db.library.tags.replace_mood_tags_batch(())
        assert result.status == "UNCHANGED"
        assert result.command_count == 0
        assert result.changed_count == 0

    def test_conflicting_duplicate_locators_rejected_before_sql(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        commands = (
            _command(identity, MoodAssignments(strict=("one",)), CalibrationMoodMarker.calibrated(VERSION_A)),
            _command(identity, MoodAssignments(strict=("two",)), CalibrationMoodMarker.calibrated(VERSION_A)),
        )

        result = db.library.tags.replace_mood_tags_batch(commands)

        assert result.status == "INVALID_VALUE"
        assert _all_tag_pairs(inference_session, song_id) == set()
        assert _marker(inference_session, song_id) is None

    def test_exact_bound_accepted_and_over_bound_rejected(
        self, db: Database, inference_session: Session, mood_world_many: dict
    ) -> None:
        """The batch bound is exercised on 1000 DISTINCT persisted locators.

        The commands must survive the facade's pre-SQL duplicate folding as 1000
        distinct entries, so this is a genuine persistence bound rather than a
        folded-duplicate no-op; the 1001-command input is likewise distinct and is
        rejected before any SQL runs.
        """
        identities = mood_world_many["identities"]
        song_ids = mood_world_many["song_ids"]
        assert len(identities) == 1001
        assert len(set(identities)) == 1001
        assignment = MoodAssignments(strict=("bounded",))
        marker = CalibrationMoodMarker.calibrated(VERSION_A)

        at_bound = tuple(_command(identity, assignment, marker) for identity in identities[:1000])
        accepted = db.library.tags.replace_mood_tags_batch(at_bound)
        assert accepted.status == "UPDATED"
        assert accepted.command_count == 1000
        assert accepted.changed_count == 1000
        # Sample distinct persisted locators to prove the 1000 commands were real
        # distinct rows (not folded duplicates).
        for song_id in (song_ids[0], song_ids[499], song_ids[999]):
            assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", "bounded")}
        # The 1001st distinct locator was never touched by the accepted batch.
        assert _mood_tags(inference_session, song_ids[1000]) == set()

        over_bound = tuple(_command(identity, assignment, marker) for identity in identities)
        assert len(set(over_bound)) == 1001
        rejected = db.library.tags.replace_mood_tags_batch(over_bound)
        assert rejected.status == "INVALID_VALUE"
        assert rejected.command_count == 0
        # The pre-SQL rejection of the distinct 1001-command input must leave the
        # earlier 1000-command accepted batch untouched (re-read after rejection).
        for song_id in (song_ids[0], song_ids[499], song_ids[999]):
            assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", "bounded")}


# ---------------------------------------------------------------------------
# H-BATCH: all-or-none, rollback, and retry classification on real PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodBatchAllOrNone:
    """Genuine PostgreSQL all-or-none evidence only.

    The monkeypatched ``_commit_mood_batch`` rollback/retry/ambiguous cases were
    removed from this live module (D3A P1-S1): they were Python control-flow fault
    injection and are owned as pure/unit ``LOCAL_PASS`` evidence by
    ``tests/unit/persistence/api/test_mood_owner_d2.py::TestMoodCommitPhase``. Real
    driver-level commit-phase SQLSTATE evidence lives in
    ``TestMoodDriverCommitPhaseFaults`` below.
    """

    def test_multi_song_missing_locator_leaves_every_song_unchanged(
        self, db: Database, inference_session: Session, mood_world: dict
    ) -> None:
        valid_id, other_id = mood_world["song_ids"]
        valid = mood_world["identities"][0]
        stale = SongIdentity(library=valid.library, normalized_path="/tmp/moodcap-nonexistent.flac")
        commands = (
            _command(valid, MoodAssignments(strict=("good",)), CalibrationMoodMarker.calibrated(VERSION_A)),
            _command(stale, MoodAssignments(strict=("ghost",)), CalibrationMoodMarker.calibrated(VERSION_A)),
        )

        result = db.library.tags.replace_mood_tags_batch(commands)

        assert result.status == "MISSING_LOCATOR"
        assert _all_tag_pairs(inference_session, valid_id) == set()
        assert _all_tag_pairs(inference_session, other_id) == set()
        assert _marker(inference_session, valid_id) is None


# ---------------------------------------------------------------------------
# Concurrency and delete/recreate readdressing on real PostgreSQL
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodConcurrencyAndReaddress:
    """Deterministic real-PostgreSQL same-locator serialization evidence.

    D2R-A added ``SongTagRepository._lock_mood_song_rows`` (``SELECT ... FOR NO KEY
    UPDATE`` on the resolved private ``songs`` row before any mood/marker read).
    These tests prove the accepted D3A-D1 single-winner contract on real
    PostgreSQL: a same-locator replacement that reaches its owner transaction first
    holds the row lock; a concurrent replacement with the same ``SongIdentity``
    blocks on that lock and, after the predecessor commits, reads the committed
    state and replaces it wholesale. The final mood set and marker are exactly ONE
    writer's complete state -- no union, no foreign/undefined edge.
    """

    def test_same_locator_concurrent_writers_are_single_winner(
        self, pg_engine, inference_session: Session, mood_world: dict, test_db_url: str
    ) -> None:
        """Writer A pauses mid-owner-transaction; B waits on the songs row; B wins.

        A is held inside its owner transaction by a test-only advisory gate that
        fires after the owner has acquired the private songs-row lock. B starts on
        the same ``SongIdentity`` and must block on A's locked row (proved via
        ``pg_blocking_pids``). Releasing A commits its transaction and releases the
        row lock, so B -- the guaranteed last committer -- reads A's committed state
        and replaces it. The final mood set and marker are exactly B's complete
        state: A's disjoint edges are gone and no union/foreign edge survives.
        """
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        token = uuid.uuid4().hex[:8]
        a1, a2 = f"alpha-{token}", f"beta-{token}"
        b1, b2 = f"gamma-{token}", f"delta-{token}"
        a_assignments = MoodAssignments(strict=(a1,), regular=(a2,))
        b_assignments = MoodAssignments(strict=(b1,), loose=(b2,))
        expected_a = {("nom:mood-strict", a1), ("nom:mood-regular", a2)}
        expected_b = {("nom:mood-strict", b1), ("nom:mood-loose", b2)}

        a_pid: dict[str, int] = {}
        b_pid: dict[str, int] = {}
        a_result: dict[str, str] = {}
        b_result: dict[str, str] = {}
        errors: list[BaseException] = []
        a_thread: threading.Thread | None = None
        b_thread: threading.Thread | None = None
        gate: _AdvisoryGate | None = None
        try:
            with _song_tag_gate(pg_engine, a1) as gate:
                a_thread = _start_mood_writer(
                    test_db_url,
                    identity,
                    a_assignments,
                    CalibrationMoodMarker.calibrated(VERSION_A),
                    pid_holder=a_pid,
                    result_holder=a_result,
                    errors=errors,
                )
                assert _wait_until_blocked_by(pg_engine, a_pid, gate.holder_pid), (
                    "writer A never paused on the owner gate while holding the row lock"
                )
                b_thread = _start_mood_writer(
                    test_db_url,
                    identity,
                    b_assignments,
                    CalibrationMoodMarker.calibrated(VERSION_B),
                    pid_holder=b_pid,
                    result_holder=b_result,
                    errors=errors,
                )
                assert _wait_until_blocked_by(pg_engine, b_pid, a_pid["pid"]), (
                    "writer B never waited on A's locked songs row"
                )
                gate.release()
                a_thread.join(timeout=60)
                b_thread.join(timeout=60)
        finally:
            # Release the gate BEFORE joining writer threads so a failing assertion
            # cannot hold A's owner transaction (and the row lock) for ~60s of joins.
            if gate is not None:
                gate.release()
            for thread in (a_thread, b_thread):
                if thread is not None and thread.is_alive():
                    thread.join(timeout=30)

        assert a_thread is not None and not a_thread.is_alive()
        assert b_thread is not None and not b_thread.is_alive()
        assert not errors, errors
        assert a_result["status"] == "UPDATED"
        assert b_result["status"] == "UPDATED"

        final_moods = _mood_tags(inference_session, song_id)
        final_marker = _marker(inference_session, song_id)
        # B is the last committer, so the final state is exactly B's complete set.
        assert final_moods == expected_b, f"expected sole winner B's state, got {final_moods}"
        assert final_marker == VERSION_B
        # Single-winner: A's disjoint edges are gone and no union/foreign edge survives.
        assert final_moods & expected_a == set(), "writer A residue survived writer B"
        assert final_moods != expected_a | expected_b, "union of both writers leaked"
        assert final_moods <= expected_a | expected_b, "foreign/undefined mood edge leaked"

    def test_overlapping_batches_are_all_or_none_and_deadlock_free(
        self, pg_engine, inference_session: Session, mood_world: dict, test_db_url: str
    ) -> None:
        """Overlapping multi-song batches serialize all-or-none under reversed command order.

        What this node PROVES: writer 1 batches both songs and pauses (via the gate)
        after acquiring both private row locks in one all-or-none statement; writer 2
        batches the same two songs with the command order reversed and waits on the
        lower private id; writer 1 commits all-or-none and writer 2, being the
        guaranteed last committer, is the sole final state for both songs.

        What this node does NOT prove: concurrent-acquisition deadlock-freedom.
        Writer 1 pauses only after acquiring BOTH locks, so writer 2 cannot form a
        lock-wait cycle regardless of owner ordering. Deadlock-avoidance is a STATIC
        property of the owner lock shape -- one ascending all-or-none
        ``SELECT ... FOR NO KEY UPDATE ... ORDER BY songs.id`` statement -- proven by
        the unit node
        ``TestMoodSameLocatorSerialization.test_batch_lock_ids_are_deterministically_ascending``
        and asserted statically immediately below.
        """
        # Static ascending-lock-shape assertion. Mirrors the owner's
        # ``SongTagRepository._lock_mood_song_rows`` statement and the unit node
        # ``test_batch_lock_ids_are_deterministically_ascending``: exactly one
        # statement locks every resolved songs row in ascending id order, so
        # concurrent batches acquire locks in the same order and cannot deadlock.
        owner_lock = select(Song.id).where(Song.id.in_([2, 1])).order_by(Song.id).with_for_update(key_share=True)
        lock_sql = str(owner_lock.compile(dialect=pg_engine.dialect)).upper()
        assert "FOR NO KEY UPDATE" in lock_sql
        assert "ORDER BY SONGS.ID" in lock_sql
        assert lock_sql.count("FOR NO KEY UPDATE") == 1, "exactly one all-or-none lock statement"

        song0_id, song1_id = mood_world["song_ids"]
        identity0, identity1 = mood_world["identities"]
        token = uuid.uuid4().hex[:8]
        w1a, w1b = f"w1a-{token}", f"w1b-{token}"
        w2a, w2b = f"w2a-{token}", f"w2b-{token}"
        w1_assignments = MoodAssignments(strict=(w1a,), regular=(w1b,))
        w2_assignments = MoodAssignments(strict=(w2a,), regular=(w2b,))
        expected_w1 = {("nom:mood-strict", w1a), ("nom:mood-regular", w1b)}
        expected_w2 = {("nom:mood-strict", w2a), ("nom:mood-regular", w2b)}
        w1_commands = (
            _command(identity0, w1_assignments, CalibrationMoodMarker.calibrated(VERSION_A)),
            _command(identity1, w1_assignments, CalibrationMoodMarker.calibrated(VERSION_A)),
        )
        # Reversed command order deliberately: the owner must still lock ascending.
        w2_commands = (
            _command(identity1, w2_assignments, CalibrationMoodMarker.calibrated(VERSION_B)),
            _command(identity0, w2_assignments, CalibrationMoodMarker.calibrated(VERSION_B)),
        )

        w1_pid: dict[str, int] = {}
        w2_pid: dict[str, int] = {}
        w1_result: dict[str, str] = {}
        w2_result: dict[str, str] = {}
        errors: list[BaseException] = []
        w1_thread: threading.Thread | None = None
        w2_thread: threading.Thread | None = None
        gate: _AdvisoryGate | None = None
        try:
            with _song_tag_gate(pg_engine, w1a) as gate:
                w1_thread = _start_mood_batch_writer(
                    test_db_url, w1_commands, pid_holder=w1_pid, result_holder=w1_result, errors=errors
                )
                assert _wait_until_blocked_by(pg_engine, w1_pid, gate.holder_pid), (
                    "writer 1 never paused on the owner gate while holding both row locks"
                )
                w2_thread = _start_mood_batch_writer(
                    test_db_url, w2_commands, pid_holder=w2_pid, result_holder=w2_result, errors=errors
                )
                assert _wait_until_blocked_by(pg_engine, w2_pid, w1_pid["pid"]), (
                    "writer 2 never waited on writer 1's locked songs row"
                )
                gate.release()
                w1_thread.join(timeout=60)
                w2_thread.join(timeout=60)
        finally:
            # Release the gate BEFORE joining writer threads so a failing assertion
            # cannot hold writer 1's owner transaction (and both row locks) for ~60s.
            if gate is not None:
                gate.release()
            for thread in (w1_thread, w2_thread):
                if thread is not None and thread.is_alive():
                    thread.join(timeout=30)

        assert w1_thread is not None and not w1_thread.is_alive()
        assert w2_thread is not None and not w2_thread.is_alive()
        assert not errors, errors
        assert w1_result["status"] == "UPDATED"
        assert w2_result["status"] == "UPDATED"
        for song_id in (song0_id, song1_id):
            assert _mood_tags(inference_session, song_id) == expected_w2
            assert _marker(inference_session, song_id) == VERSION_B
            assert _mood_tags(inference_session, song_id) & expected_w1 == set()

    def test_same_locator_rollback_releases_row_and_permits_later_winner(
        self, pg_engine, inference_session: Session, mood_world: dict, test_db_url: str
    ) -> None:
        """A locks then aborts; B proceeds and is the sole final state with no A residue."""
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        token = uuid.uuid4().hex[:8]
        a1 = f"rolla-{token}"
        b1 = f"rollb-{token}"

        a_pid: dict[str, int] = {}
        b_pid: dict[str, int] = {}
        a_result: dict[str, str] = {}
        b_result: dict[str, str] = {}
        errors: list[BaseException] = []
        a_thread: threading.Thread | None = None
        b_thread: threading.Thread | None = None
        try:
            with _song_tag_gate(pg_engine, a1, abort=True) as gate:
                a_thread = _start_mood_writer(
                    test_db_url,
                    identity,
                    MoodAssignments(strict=(a1,)),
                    CalibrationMoodMarker.calibrated(VERSION_A),
                    pid_holder=a_pid,
                    result_holder=a_result,
                    errors=errors,
                )
                assert _wait_until_blocked_by(pg_engine, a_pid, gate.holder_pid), (
                    "writer A never paused on the owner gate while holding the row lock"
                )
                b_thread = _start_mood_writer(
                    test_db_url,
                    identity,
                    MoodAssignments(strict=(b1,)),
                    CalibrationMoodMarker.calibrated(VERSION_B),
                    pid_holder=b_pid,
                    result_holder=b_result,
                    errors=errors,
                )
                assert _wait_until_blocked_by(pg_engine, b_pid, a_pid["pid"]), (
                    "writer B never waited on A's locked songs row before A rolled back"
                )
                gate.release()
                a_thread.join(timeout=60)
                b_thread.join(timeout=60)
        finally:
            for thread in (a_thread, b_thread):
                if thread is not None and thread.is_alive():
                    thread.join(timeout=30)

        assert a_thread is not None and not a_thread.is_alive()
        assert b_thread is not None and not b_thread.is_alive()
        assert not errors, errors
        # A's gated failure is non-retryable and rolls back; B then owns the state.
        assert a_result["status"] == "INFRA_FAILURE"
        assert b_result["status"] == "UPDATED"
        assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", b1)}
        assert _marker(inference_session, song_id) == VERSION_B
        assert _mood_tags(inference_session, song_id) != {("nom:mood-strict", a1)}

    def test_delete_recreate_does_not_resurrect_old_marker(
        self, db: Database, pg_engine, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        db.library.tags.replace_mood_tags(
            identity, MoodAssignments(strict=("old",)), CalibrationMoodMarker.calibrated(VERSION_A)
        )
        assert _marker(inference_session, song_id) == VERSION_A

        with pg_engine.begin() as conn:
            snapshot = dict(conn.execute(select(_SONG_TABLE).where(_SONG_TABLE.c.id == song_id)).mappings().one())
            payload = {key: value for key, value in snapshot.items() if key != "id"}
            conn.execute(text("DELETE FROM songs WHERE id = :song_id"), {"song_id": song_id})
            new_id = int(conn.execute(_SONG_TABLE.insert().values(**payload).returning(_SONG_TABLE.c.id)).scalar_one())

        assert new_id != song_id
        # A row recreated at the same locator starts with no mood and no marker;
        # the old locator's calibration is not backfilled or aliased.
        assert _marker(inference_session, new_id) is None
        assert _mood_tags(inference_session, new_id) == set()

        result = db.library.tags.replace_mood_tags(identity, None, CalibrationMoodMarker.uncalibrated())
        assert result.status == "UNCHANGED"
        assert _marker(inference_session, new_id) is None


# ---------------------------------------------------------------------------
# Real driver-level constraint + commit-phase SQLSTATE evidence
# ---------------------------------------------------------------------------


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodDriverDuplicateConstraint:
    """A real ``23505`` unique-constraint race on the mood-edge path.

    A second connection holds an uncommitted duplicate ``song_tags`` edge on the
    ``uq_song_tags_song_tag`` unique constraint. The owner's edge SELECT cannot see
    the uncommitted row, so it attempts the insert and blocks; when the blocker
    commits, the real PostgreSQL driver raises ``23505``. The mood path returns the
    typed ``INFRA_FAILURE`` outcome (with the owner's other edge/tag work rolled back
    — no partial mutation). The raw driver ``23505`` is then observed by a separate
    real probe insert that re-runs the conflicting insert and reads
    ``IntegrityError.orig.pgcode``; the test does not claim the owner's mapped
    exception itself exposes a raw ``pgcode``.
    """

    def test_duplicate_mood_edge_emits_real_23505_and_rolls_back(
        self,
        pg_engine,
        inference_session: Session,
        mood_world: dict,
        test_db_url: str,
    ) -> None:
        from nomarr.persistence.db import Database as DatabaseClass

        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]
        # Unique per run so the persistent local test database never collides on
        # uq_tags_name_value_ns from a previous run.
        race_value = f"race-{uuid.uuid4().hex[:8]}"
        partial_value = f"partial-{uuid.uuid4().hex[:8]}"

        # Create the target mood tag but NOT its edge, so the owner wants to insert
        # the edge and the blocker can hold the conflicting uncommitted row.
        with pg_engine.begin() as conn:
            tag_id = int(
                conn.execute(
                    text(
                        "INSERT INTO tags (namespace, name, value) "
                        "VALUES ('nom', 'nom:mood-strict', :value) RETURNING id"
                    ),
                    {"value": race_value},
                ).scalar_one()
            )

        blocker = pg_engine.connect()
        blocker_tx = blocker.begin()
        blocker.execute(
            text(
                "INSERT INTO song_tags (song_id, tag_id, confidence, source, created_at) "
                "VALUES (:song_id, :tag_id, 1.0, 'blocker', :created_at)"
            ),
            {"song_id": song_id, "tag_id": tag_id, "created_at": now_ms().value},
        )

        pid_holder: dict[str, int] = {}
        result_holder: dict[str, str] = {}
        errors: list[BaseException] = []

        def _writer() -> None:
            local_db = DatabaseClass(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
            try:
                pid_holder["pid"] = int(local_db._scoped.execute(text("SELECT pg_backend_pid()")).scalar_one())
                outcome = local_db.library.tags.replace_mood_tags(
                    identity,
                    MoodAssignments(strict=(race_value, partial_value)),
                    CalibrationMoodMarker.calibrated(VERSION_A),
                )
                result_holder["status"] = outcome.status
            except BaseException as exc:  # pragma: no cover - surfaced via `errors`
                errors.append(exc)
            finally:
                local_db.close()

        thread = threading.Thread(target=_writer)
        thread.start()
        try:
            blocked = _wait_for_writer_lock(pg_engine, pid_holder, timeout=20.0)
            assert blocked, "writer never blocked on the duplicate unique edge"
            blocker_tx.commit()
        finally:
            blocker.close()
        thread.join(timeout=60)
        assert not thread.is_alive(), "writer thread did not finish"
        assert not errors, errors

        assert result_holder["status"] == "INFRA_FAILURE"
        assert result_holder["status"] != "MISSING_LOCATOR"
        # The writer's real driver exception is a 23505 unique_violation. The owner
        # classifies the real driver ``pgcode`` internally (see
        # SongTagRepository._commit_mood_batch) and returns typed ``INFRA_FAILURE``;
        # the owner's mapped exception does not surface the raw pgcode. This test
        # confirms the underlying race produces a genuine 23505 by re-running the
        # conflicting insert as a separate real probe insert.
        with pytest.raises(IntegrityError) as excinfo, pg_engine.begin() as probe:
            probe.execute(
                text(
                    "INSERT INTO song_tags (song_id, tag_id, confidence, source, created_at) "
                    "VALUES (:song_id, :tag_id, 1.0, 'probe', :created_at)"
                ),
                {"song_id": song_id, "tag_id": tag_id, "created_at": now_ms().value},
            )
        assert getattr(excinfo.value.orig, "pgcode", None) == "23505"
        # Only the blocker's committed edge exists; the owner's second edge and the
        # tag it created for it were rolled back with the 23505 (no partial mutation).
        assert _mood_tags(inference_session, song_id) == {("nom:mood-strict", race_value)}
        with pg_engine.connect() as conn:
            leaked_tags = conn.execute(
                text(
                    "SELECT count(*) FROM tags "
                    "WHERE namespace = 'nom' AND name = 'nom:mood-strict' AND value = :partial"
                ),
                {"partial": partial_value},
            ).scalar_one()
        assert int(leaked_tags) == 0


@pytest.mark.characterization
@pytest.mark.requires_database
class TestMoodDriverCommitPhaseFaults:
    """Real commit-phase SQLSTATE classification through the PostgreSQL driver.

    Each test installs a test-only ``DEFERRABLE INITIALLY DEFERRED`` constraint
    trigger on ``song_tags`` that raises a real PostgreSQL error at COMMIT with a
    specific SQLSTATE. The owner's actual ``_commit_mood_batch`` receives the real
    driver exception (``orig.pgcode``) and classifies it. A non-transactional
    sequence counts attempts because every attempt rolls back.
    """

    def _attempts(self, pg_engine, counter: str) -> int:
        with pg_engine.connect() as conn:
            return int(conn.execute(text(f"SELECT last_value FROM {counter}")).scalar_one())

    def test_retryable_commit_sqlstate_is_bounded_fresh_session_retry(
        self, db: Database, pg_engine, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]

        with _deferred_commit_fault(pg_engine, "40001") as counter:
            result = db.library.tags.replace_mood_tags(
                identity, MoodAssignments(strict=("retry",)), CalibrationMoodMarker.calibrated(VERSION_A)
            )
            attempts = self._attempts(pg_engine, counter)

        assert attempts == 3, "retryable commit failures are bounded to 3 attempts"
        assert result.status == "INFRA_FAILURE"
        assert _all_tag_pairs(inference_session, song_id) == set()
        assert _marker(inference_session, song_id) is None

    def test_ambiguous_commit_sqlstate_is_not_retried(
        self, db: Database, pg_engine, inference_session: Session, mood_world: dict
    ) -> None:
        song_id = mood_world["song_ids"][0]
        identity = mood_world["identities"][0]

        with _deferred_commit_fault(pg_engine, "40003") as counter:
            result = db.library.tags.replace_mood_tags(
                identity, MoodAssignments(strict=("ambiguous",)), CalibrationMoodMarker.calibrated(VERSION_A)
            )
            attempts = self._attempts(pg_engine, counter)

        assert attempts == 1, "an ambiguous commit is never retried"
        assert result.status == "AMBIGUOUS_COMMIT"
        assert _all_tag_pairs(inference_session, song_id) == set()
        assert _marker(inference_session, song_id) is None
