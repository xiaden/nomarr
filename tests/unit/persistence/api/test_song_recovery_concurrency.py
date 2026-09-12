"""M recovery/concurrency evidence that is executable without PostgreSQL.

Real transaction isolation, concurrent claim/upsert/remove, SQLSTATE, connection-loss,
and mood-owner evidence belongs to the CI database tier and is documented in the
M handoff. These tests pin the local, deterministic boundary semantics: poisoned
sessions are disposed, ambiguous commits are not completed blindly, immutable
locators/claims are used for restart, and errors are redacted at the presentation
boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from nomarr.components.workers.worker_discovery_comp import claim_file, release_claim
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity
from nomarr.helpers.exceptions import AmbiguousCommitError, RetryableDatabaseError
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.persistence.database.song_repo import SongRepository

_LIBRARY = LibraryIdentity(
    library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd",
    name="TestLib",
    root_path="/music",
)
_SONG = SongIdentity(library=_LIBRARY, normalized_path="album/a.mp3")


def _operational_error(pgcode: str) -> OperationalError:
    original = Mock()
    original.pgcode = pgcode
    return OperationalError("database failure", params=None, orig=original)


def _repo_with_session() -> tuple[SongRepository, MagicMock]:
    session = MagicMock()
    session.begin_nested.return_value.__enter__.return_value = None
    return SongRepository(session), session


class _FakeResult:
    """Minimal SQLAlchemy-result double carrying a row and/or rowcount."""

    def __init__(self, *, row: object | None = None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    def first(self) -> object | None:
        return self._row


def _repo_with_scalar_session(
    *,
    selected: object | None,
    rowcount: int = 0,
) -> tuple[SongRepository, MagicMock]:
    """Repository over a mock session whose SELECT yields *selected*.

    The repository's scalar writers execute a locator SELECT followed (only for a
    detectable write) by an UPDATE. ``execute`` returns the SELECT result first; a
    rowcount-bearing UPDATE result is configured as the second return value so the
    conditional-update branch can report UPDATED vs STALE_VALUE by ``rowcount``.
    """
    repo, session = _repo_with_session()
    session.execute.side_effect = [
        _FakeResult(row=selected),
        _FakeResult(rowcount=rowcount),
    ]
    return repo, session


@pytest.mark.unit
@pytest.mark.parametrize("pgcode", ["40001", "40P01", "55P03"])
def test_retryable_sqlstates_dispose_poisoned_session(pgcode: str) -> None:
    """Retryable failures never reuse a failed session or silently complete."""
    repo, session = _repo_with_session()
    session.execute.side_effect = _operational_error(pgcode)

    with pytest.raises(RetryableDatabaseError):
        repo.set_modified_time_by_locator(7, _SONG.normalized_path, 100)

    session.rollback.assert_called_once()
    session.remove.assert_called_once()
    session.commit.assert_not_called()


@pytest.mark.unit
def test_unknown_commit_is_ambiguous_after_rollback_and_disposal() -> None:
    """A lost commit acknowledgement requires authorized readback/re-addressing."""
    repo, session = _repo_with_session()
    result = MagicMock()
    result.first.return_value = (10,)
    session.execute.return_value = result
    session.commit.side_effect = _operational_error("40003")

    with pytest.raises(AmbiguousCommitError):
        repo.set_last_tagged_by_locator(7, _SONG.normalized_path, 20)

    session.rollback.assert_called_once()
    session.remove.assert_called_once()
    # The repository does not perform blind completion or an implicit readback.
    assert session.execute.call_count == 2


@pytest.mark.unit
def test_restart_command_and_claim_are_immutable_locator_values() -> None:
    """A restart can rehydrate the command and claim without a generated ID."""
    identity = WorkerClaimIdentity(song=_SONG, worker_id="worker:discovery:1", claim_type=None)
    claim = WorkerClaim(identity=identity, claimed_at_ms=1234)
    assert claim.identity.song == _SONG
    assert claim.identity.worker_id == "worker:discovery:1"
    assert not hasattr(claim, "song_id")
    with pytest.raises((AttributeError, TypeError)):
        claim.claimed_at_ms = 1235  # type: ignore[misc]


@pytest.mark.unit
def test_claim_acquire_and_release_use_same_locator_without_id_fallback() -> None:
    """Recovery cleanup addresses the exact claim identity, not a storage handle."""
    db = MagicMock()
    db.app.add_claim.return_value = True

    assert claim_file(db, _SONG, "worker:discovery:1") is True
    release_claim(db, _SONG, "worker:discovery:1")

    acquired = db.app.add_claim.call_args.args[0]
    released = db.app.remove_claim.call_args.args[0]
    assert acquired.identity.song == _SONG
    assert released.song == _SONG
    assert not hasattr(acquired, "song_id")
    assert not hasattr(released, "song_id")


@pytest.mark.unit
def test_redaction_hides_locator_storage_and_connection_details(caplog: pytest.LogCaptureFixture) -> None:
    """Presentation errors stay coarse while diagnostics remain available to logs."""
    unsafe = ValueError("/music/album/a.mp3 library_uuid=secret songs.id=42 postgresql://user:pw@db/app")
    safe = sanitize_exception_message(unsafe, "Unable to recover song operation")
    assert safe == "Unable to recover song operation"
    assert "/music/album/a.mp3" not in safe
    assert "secret" not in safe
    assert "42" not in safe
    assert "postgresql://" not in safe
    assert any("Exception sanitized" in record.message for record in caplog.records)


# ── R2-3: direct repository comparison logic (mock session) ────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    ("selected", "value", "rowcount", "expected"),
    [
        (1000, 2000, 1, "UPDATED"),  # greater than stored -> conditional update
        (1000, 1000, 0, "UNCHANGED"),  # equal -> no update statement
        (1000, 500, 0, "STALE_VALUE"),  # lower than stored -> monotonic reject
        (None, 2000, 0, "MISSING_LOCATOR"),  # no row for locator
        (1000, 2000, 0, "STALE_VALUE"),  # raced UPDATE rowcount zero
    ],
)
def test_monotonic_scalar_repository_comparison(
    selected: object | None, value: int, rowcount: int, expected: str
) -> None:
    """``_set_monotonic_scalar`` decides UPDATED/UNCHANGED/STALE/MISSING in-repo.

    Direct behavioral coverage of the repository comparison (not the facade
    relay): greater writes, equal is UNCHANGED without an update, lower is
    STALE_VALUE, an absent row is MISSING_LOCATOR, and a raced UPDATE reporting
    ``rowcount == 0`` degrades to STALE_VALUE rather than claiming a write.
    """
    repo, session = _repo_with_scalar_session(selected=(selected,) if selected is not None else None, rowcount=rowcount)

    assert repo.set_modified_time_by_locator(7, _SONG.normalized_path, value) == expected

    if expected == "UNCHANGED":
        # equal never issues the conditional UPDATE
        assert session.execute.call_count == 1
    elif expected == "UPDATED":
        assert session.execute.call_count == 2
    else:
        assert session.execute.call_count <= 2
    session.commit.assert_called_once()
    session.rollback.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("selected", "value", "expected_value", "expected_absent", "rowcount", "expected"),
    [
        (None, "NEW", None, True, 0, "MISSING_LOCATOR"),  # absent song row -> no location
        ("OLD", "NEW", "OLD", False, 1, "UPDATED"),  # matching precondition -> write
        ("OLD", "NEW", None, True, 0, "STALE_VALUE"),  # expected_absent, slot occupied
        ("OLD", "NEW", "WRONG", False, 0, "STALE_VALUE"),  # expected_value mismatch
        ("NEW", "NEW", "NEW", False, 0, "UNCHANGED"),  # equal -> no write
        (None, "NEW", "OLD", False, 0, "MISSING_LOCATOR"),  # absent song row -> no location
        ("OLD", "NEW", "OLD", False, 0, "STALE_VALUE"),  # raced UPDATE rowcount zero
    ],
)
def test_guarded_chromaprint_repository_preconditions(
    selected: object | None,
    value: str,
    expected_value: str | None,
    expected_absent: bool,
    rowcount: int,
    expected: str,
) -> None:
    """``set_chromaprint_by_locator`` enforces caller preconditions in-repo.

    Direct behavioral coverage of the guarded replacement: ``expected_absent``
    fails when an old value exists, ``expected_value`` must match the current
    value, an equal current value is UNCHANGED without a write, an absent row is
    MISSING_LOCATOR, and a raced UPDATE with ``rowcount == 0`` is STALE_VALUE.
    """
    repo, session = _repo_with_scalar_session(selected=(selected,) if selected is not None else None, rowcount=rowcount)

    assert (
        repo.set_chromaprint_by_locator(
            7,
            _SONG.normalized_path,
            value,
            expected_value=expected_value,
            expected_absent=expected_absent,
        )
        == expected
    )
    if expected == "UNCHANGED":
        assert session.execute.call_count == 1
    session.commit.assert_called_once()
    session.rollback.assert_not_called()


@pytest.mark.unit
def test_monotonic_scalar_missing_row_is_not_written() -> None:
    """A locator with no row writes nothing and still commits its empty txn."""
    repo, session = _repo_with_scalar_session(selected=None)

    assert repo.set_last_tagged_by_locator(7, _SONG.normalized_path, 20) == "MISSING_LOCATOR"

    session.execute.assert_called_once()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
