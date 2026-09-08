"""Atomic Song-move intent characterization on real PostgreSQL.

Real-DB proof of the ADR-047 §2/§8 move contract exercised end-to-end through
``db.library.move_library_song(SongPathUpdate)``:

- One atomic intent updates the existing row in place (stable ``song_id`` /
  unchanged owning library) with every locator + scan field committing together.
- Song associations (the seed tag assignments) stay attached across a move —
  the move never inserts/deletes/recreates a row.
- A destination uniqueness conflict on ``(library_id, path)`` or
  ``(library_id, normalized_path)`` raises ``DuplicateEntityError`` (Postgres
  pgcode 23505) and rolls back the entire move, leaving the original row AND its
  associations unchanged (no partial row state).
- A missing/stale identity raises ``LookupError`` and fabricates no replacement.

Uses the real pgvector:pg17 container (PostgreSQL-only pgcode 23505 →
``DuplicateEntityError`` translation that SQLite cannot reproduce), so this
module is marked ``characterization`` + ``requires_database`` and runs only in
the CI ``database-tests`` job. It is NOT runnable in this workspace (no Docker);
it is authored as the P3-S7 concurrency/atomicity oracle the persistence layer
promises. Atomicity here is the single-``UPDATE``/single-commit guarantee — with
the container available this file documents and locks that property on a real
PostgreSQL engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import func, select

from nomarr.helpers.dataclasses.song_command_dataclass import SongPathUpdate, SongScanUpdate
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from nomarr.persistence.db import Database

_SONG_TABLE = Song.__table__
_SONG_TAG_TABLE = SongTag.__table__


def _row(session: Session, song_id: int) -> dict:
    stmt = select(_SONG_TABLE).where(_SONG_TABLE.c.id == song_id)
    result = session.execute(stmt).first()
    assert result is not None, f"song {song_id} missing"
    return dict(result._mapping)


def _tag_assignment_count(session: Session, song_id: int) -> int:
    stmt = select(func.count()).select_from(_SONG_TAG_TABLE).where(_SONG_TAG_TABLE.c.song_id == song_id)
    return int(session.execute(stmt).scalar_one())


def _move_command(song_id: int, path: str, *, scanned_at: int | None = None) -> SongPathUpdate:
    return SongPathUpdate(
        song_id=song_id,
        new_path=path,
        scan=SongScanUpdate(
            normalized_path=path,
            file_size=1024000,
            modified_time=now_ms().value,
            duration_seconds=180.5,
            is_valid=True,
            scanned_at=scanned_at,
        ),
    )


@pytest.mark.characterization
@pytest.mark.requires_database
class TestSongMoveAtomicIntent:
    """End-to-end atomic move intent on real PostgreSQL."""

    def test_move_updates_in_place_and_keeps_associations(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """The move commits locator + scan together on the SAME row; the seed
        tag associations stay attached (no delete/recreate)."""
        target = cast("int", seed_data["songs"][0])
        before = _row(inference_session, target)
        association_before = _tag_assignment_count(inference_session, target)
        assert association_before > 0, "seed song must carry tag associations to prove retention"

        db.library.move_library_song(_move_command(target, "/tmp/test1/song1-moved.flac", scanned_at=9000))

        after = _row(inference_session, target)
        # Same stable identity and owning library → updated in place.
        assert after["id"] == target
        assert after["library_id"] == before["library_id"]
        assert after["path"] == "/tmp/test1/song1-moved.flac"
        assert after["normalized_path"] == "/tmp/test1/song1-moved.flac"
        assert after["scanned_at"] == 9000
        # Associations stayed attached to the unchanged row.
        assert _tag_assignment_count(inference_session, target) == association_before

    def test_path_uniqueness_conflict_raises_and_leaves_no_partial_state(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """Moving onto a sibling's path raises DuplicateEntityError and rolls back
        the whole move — locator and scan fields stay at their original values."""
        target = cast("int", seed_data["songs"][0])
        sibling_path = _row(inference_session, cast("int", seed_data["songs"][1]))["path"]
        before = _row(inference_session, target)
        association_before = _tag_assignment_count(inference_session, target)

        with pytest.raises(DuplicateEntityError):
            db.library.move_library_song(_move_command(target, sibling_path, scanned_at=7777))

        after = _row(inference_session, target)
        for col in (
            "path",
            "normalized_path",
            "file_size",
            "modified_time",
            "duration_seconds",
            "is_valid",
            "scanned_at",
        ):
            assert after[col] == before[col], f"'{col}' must roll back on uniqueness conflict"
        assert _tag_assignment_count(inference_session, target) == association_before

    def test_normalized_path_uniqueness_conflict_rolls_back(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        """A collision on (library_id, normalized_path) — even with a distinct
        physical path — rolls back the whole move atomically."""
        target = cast("int", seed_data["songs"][0])
        _row(inference_session, cast("int", seed_data["songs"][1]))["normalized_path"]
        before = _row(inference_session, target)

        with pytest.raises(DuplicateEntityError):
            db.library.move_library_song(_move_command(target, "/tmp/test1/physically-distinct.mp3"))

        after = _row(inference_session, target)
        assert after["normalized_path"] == before["normalized_path"]
        assert after["path"] == before["path"]

    def test_missing_identity_raises_lookup_error_without_replacement(
        self, db: Database, inference_session: Session, seed_data: dict
    ) -> None:
        with pytest.raises(LookupError):
            db.library.move_library_song(_move_command(99999999, "/tmp/test1/ghost.mp3"))

        # No replacement row is fabricated for a stale/missing identity.
        stmt = select(_SONG_TABLE).where(_SONG_TABLE.c.path == "/tmp/test1/ghost.mp3")
        assert inference_session.execute(stmt).first() is None
