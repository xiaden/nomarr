"""Real PostgreSQL hydration/admission serialization evidence."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.hydration_dto import HydrateSongInput
from nomarr.helpers.time_helper import internal_ms, now_ms
from nomarr.persistence.db import Database


def _identity(library: Library, library_uuid: str) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid=library_uuid, name=library.name, root_path=library.root_path),
        normalized_path=f"{library.root_path}/song.flac",
    )


def _input() -> HydrateSongInput:
    return HydrateSongInput(
        parsed_nom_tags={}, entity_tags={"genre": ["test"]}, metadata_cache={}, duration_seconds=None
    )


@pytest.mark.characterization
@pytest.mark.requires_database
class TestHydrationAdmissionConcurrency:
    def test_tag_write_admission_blocks_while_hydration_holds_parent_lock(
        self, db: Database, pg_engine, test_db_url: str
    ) -> None:
        suffix = uuid.uuid4().hex[:10]
        library = db.library.create_library(Library(name=f"Hydration-{suffix}", root_path=f"/tmp/hydration-{suffix}"))
        blocker = pg_engine.connect()
        try:
            with pg_engine.begin() as connection:
                row = connection.execute(
                    text("SELECT id, library_uuid FROM libraries WHERE name = :name"), {"name": library.name}
                ).one()
                library_id, _library_uuid = int(row[0]), str(row[1])
                now = now_ms().value
                connection.execute(
                    text(
                        "INSERT INTO songs (library_id, path, normalized_path, file_size, modified_time, created_at) "
                        "VALUES (:library_id, :path, :path, 1000, :now, :now)"
                    ),
                    {"library_id": library_id, "path": f"{library.root_path}/song.flac", "now": now},
                )
                connection.execute(text("DELETE FROM pipeline_states WHERE library_id = :id"), {"id": library_id})

            blocker.execute(text("SELECT id FROM libraries WHERE id = :id FOR UPDATE"), {"id": library_id})
            blocker_pid = int(blocker.execute(text("SELECT pg_backend_pid()")).scalar_one())
            result: dict[str, Any] = {}
            errors: list[BaseException] = []

            def run() -> None:
                local_db = Database(url=test_db_url, echo=False, pool_size=1, max_overflow=0)
                try:
                    result["pid"] = int(local_db._scoped.execute(text("SELECT pg_backend_pid()")).scalar_one())
                    result["state"] = local_db.library.admit_tag_write(library)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    local_db.close()

            thread = threading.Thread(target=run)
            thread.start()
            deadline = internal_ms().value + 20_000
            while internal_ms().value < deadline and "pid" not in result:
                time.sleep(0.02)
            assert "pid" in result
            while internal_ms().value < deadline:
                with pg_engine.connect() as connection:
                    blockers = connection.execute(
                        text("SELECT pg_blocking_pids(:pid)"), {"pid": result["pid"]}
                    ).scalar_one()
                if blocker_pid in set(blockers or ()):
                    break
                time.sleep(0.02)
            else:
                pytest.fail("tag-write admission was not observed waiting on parent library lock")
            blocker.commit()
            thread.join(timeout=30)
            assert not thread.is_alive()
            assert not errors
            assert isinstance(result.get("state"), dict)
        finally:
            blocker.close()
            db.library.remove_library(library)
