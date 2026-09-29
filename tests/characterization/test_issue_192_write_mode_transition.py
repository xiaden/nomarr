"""Real PostgreSQL evidence for the Issue #192 write-mode transition invariants.

The dedicated ``PATCH /library/{name}/write-mode`` transition must be coherent and
serialized: the persisted mode and the ``tags_current`` → ``tags_not_fresh``
invalidation commit together, an admitted tag write blocks the change instead of
being silently overwritten, and the committed result is visible to a fresh
connection (restart). These run in the ``database-tests`` CI tier; locally they
require ``NOMARR_TEST_DATABASE_URL`` (or the testcontainer fallback).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from nomarr.helpers.constants.file_states import (
    STATE_HYDRATED,
    STATE_NOT_HYDRATED,
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.exceptions import LibraryOperationConflict
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database

pytestmark = [pytest.mark.characterization, pytest.mark.requires_database]


def _seed(db: Database, n: int = 3) -> tuple[Library, list[SongIdentity]]:
    """Create an isolated library with ``n`` hydrated, written, tags-current songs."""
    suffix = uuid.uuid4().hex[:10]
    name = f"WriteMode-{suffix}"
    root = f"/tmp/write-mode-{suffix}"
    library = db.library.create_library(Library(name=name, root_path=root, file_write_mode="full"))
    library_identity = LibraryIdentity(
        library_uuid=library.library_uuid or "00000000-0000-0000-0000-000000000000",
        name=library.name,
        root_path=library.root_path,
    )
    now = now_ms().value
    identities: list[SongIdentity] = []
    for index in range(n):
        normalized_path = f"track{index}.flac"
        scan = SongScanUpdate(
            normalized_path=normalized_path,
            file_size=1000 + index,
            modified_time=now,
            duration_seconds=180.0,
        )
        identities.append(
            db.library.add_song_to_library(
                SongUpsertInput(library=library_identity, path=f"{root}/{normalized_path}", scan=scan)
            )
        )
    for identity in identities:
        db.app.transition_song_states([identity], STATE_NOT_WRITTEN, STATE_WRITTEN)
        db.app.transition_song_states([identity], STATE_TAGS_NOT_FRESH, STATE_TAGS_CURRENT)
        db.app.transition_song_states([identity], STATE_NOT_HYDRATED, STATE_HYDRATED)
    return library, identities


def _persisted_mode(pg_engine, library: Library) -> str:
    with pg_engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT file_write_mode FROM libraries WHERE name = :name"), {"name": library.name}
            ).scalar_one()
        )


class TestWriteModeTransitionLifecycle:
    def test_mode_change_persists_and_invalidates_together(self, db: Database, pg_engine) -> None:
        library, identities = _seed(db)
        try:
            affected = db.library.change_write_mode(library, "minimal")

            assert affected == len(identities)
            assert _persisted_mode(pg_engine, library) == "minimal"
            for identity in identities:
                membership = db.app.song_state_membership(identity)
                assert "tags_not_fresh" in membership
                assert "tags_current" not in membership
        finally:
            db.library.remove_library(library)

    def test_mode_change_conflicts_while_tag_write_admitted(self, db: Database, pg_engine) -> None:
        library, identities = _seed(db)
        try:
            admitted = db.library.admit_tag_write(library)
            assert admitted.tag_write_state == "writing"

            with pytest.raises(LibraryOperationConflict) as exc_info:
                db.library.change_write_mode(library, "minimal")

            assert exc_info.value.operation == "write_mode"
            assert exc_info.value.tag_write_state == "writing"
            # No side effects: neither the mode nor the freshness state moved.
            assert _persisted_mode(pg_engine, library) == "full"
            for identity in identities:
                membership = db.app.song_state_membership(identity)
                assert "tags_current" in membership
                assert "tags_not_fresh" not in membership
        finally:
            db.library.remove_library(library)

    def test_mode_change_is_visible_to_a_fresh_connection(self, db: Database, test_db_url: str) -> None:
        library, identities = _seed(db)
        fresh = Database(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
        try:
            affected = db.library.change_write_mode(library, "minimal")
            assert affected == len(identities)

            # A separate connection (simulated restart) observes the committed
            # mode and the committed freshness transition.
            reloaded = fresh.library.get_library_by_name(library.name)
            assert reloaded is not None
            assert reloaded.file_write_mode == "minimal"
            for identity in identities:
                membership = fresh.app.song_state_membership(identity)
                assert "tags_not_fresh" in membership
                assert "tags_current" not in membership

            # A retry from the restarted process is coherent and idempotent:
            # no remaining tags_current candidates and the mode still applies.
            assert fresh.library.change_write_mode(reloaded, "minimal") == 0
            retried = fresh.library.get_library_by_name(library.name)
            assert retried is not None
            assert retried.file_write_mode == "minimal"
        finally:
            fresh.close()
            db.library.remove_library(library)
