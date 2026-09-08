"""Restart/lifecycle evidence for the atomic library reset aggregate.

P2-S1 of ``TASK-library-reset-persistence-choreography-D-behavior-docs``: prove that a
successful ``reset_library_data`` commit is *durable* — the documented cleared rows
stay absent and the preserved-boundary rows stay present after the database is closed
and reopened.

Harness limitation
------------------
The production maintenance surface is reached through ``Database`` / ``LibraryDb``
over real PostgreSQL (pgvector), which needs a Docker-backed container unavailable in
this environment. We therefore follow the SQLite convention used by the sibling
repository tests (``tests/unit/persistence/database/conftest.py``) and exercise the
exact facade delegate ``LibraryMaintenanceDb.reset_library_data()``, which forwards to
``LibraryResetRepo``. Because that repo owns one repository ``begin_nested``/``commit``
boundary and commits durably, restart semantics are proven with the next-best
equivalent to a full ``Database`` close/reopen: the reset is committed on a durable
temp-file SQLite engine, the engine is disposed, and a brand-new engine + session on
the same file re-reads committed state to assert clear/preserve held after reopen.

The pgvector ``embeddings`` table cannot compile for SQLite (HALFVEC), so it is
materialised as a minimal SQLite-compatible table (id/song_id/backbone_id) exactly as
the sibling tests do; only row presence/absence matters for the reset. SQLite does not
enforce ``ON DELETE CASCADE`` by default, so the ``ml_embedding_streams`` row
(referencing a cleared song) survives the song delete — matching the preserved-boundary
semantics the reset targets (the physical-cascade nuance is documented separately in
the repository/characterization notes).
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import create_engine, func, insert, select, text
from sqlalchemy.orm import Session

from nomarr.persistence.api.library import LibraryMaintenanceDb
from nomarr.persistence.database.library_reset_repo import LibraryResetRepo
from nomarr.persistence.models.calibration_state import CalibrationState
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_folder import LibraryFolder
from nomarr.persistence.models.library_scan import LibraryScan
from nomarr.persistence.models.ml_embedding_stream import MlEmbeddingStream
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.models.ml_model_output import MlModelOutput
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.models.pipeline_state import PipelineState
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_state import SongState
from nomarr.persistence.models.song_state_assignment import SongStateAssignment
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.models.worker_claim import WorkerClaim

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

_LIBRARY_NAMES = count(1)

# Minimal SQLite-compatible stand-in for the pgvector ``embeddings`` table.
_EMBEDDINGS_DDL = """
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER NOT NULL,
    backbone_id VARCHAR(100) NOT NULL
)
"""

# Tables a successful reset must leave empty after reopen.
_CLEARED_TABLE_NAMES = (
    "embeddings",
    "ml_output_streams",
    "pipeline_states",
    "song_tags",
    "song_state_assignments",
    "songs",
    "library_folders",
    "tags",
    "library_scans",
)

# Preserved-boundary tables whose seeded rows must survive reopen.
_PRESERVED_TABLES = {
    "libraries": Library.__table__,
    "ml_models": MlModel.__table__,
    "ml_model_outputs": MlModelOutput.__table__,
    "calibration_states": CalibrationState.__table__,
    "worker_health": Health.__table__,
    "worker_claims": WorkerClaim.__table__,
    "song_states": SongState.__table__,
    "ml_embedding_streams": MlEmbeddingStream.__table__,
}


def _build_engine(db_path: Path) -> Engine:
    """Create a fresh durable SQLite engine with the schema and minimal embeddings."""
    import nomarr.persistence.models as _models  # noqa: F401 — registers Base tables
    from nomarr.persistence.models.base import Base

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    safe_tables = [t for t in Base.metadata.sorted_tables if t.name != "embeddings"]
    Base.metadata.create_all(engine, tables=safe_tables)
    with engine.begin() as conn:
        conn.execute(text(_EMBEDDINGS_DDL))
    return engine


def _count(session: Session, table) -> int:
    """Return the current row count of *table*."""
    return int(session.execute(select(func.count()).select_from(table)).scalar_one())


def _insert_pk(session: Session, stmt) -> int:
    """Execute an INSERT and return its autoincrement primary key."""
    result = session.execute(stmt)
    return int(cast("Any", result).inserted_primary_key[0])


def _seed_library(session: Session, path: str = "/lifecycle/lib") -> int:
    return _insert_pk(
        session,
        insert(Library).values(
            name=f"Lifecycle Lib {next(_LIBRARY_NAMES)}",
            path=path,
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        ),
    )


def _seed_song(session: Session, library_id: int, folder_id: int | None, path: str) -> int:
    return _insert_pk(
        session,
        insert(Song).values(
            library_id=library_id,
            folder_id=folder_id,
            path=path,
            normalized_path=path,
            file_size=1024,
            modified_time=1000,
            duration_seconds=180,
            chromaprint=None,
            needs_tagging=1,
            is_valid=1,
            tagged=0,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=1000,
            created_at=1000,
        ),
    )


def _seed_lifecycle_world(session: Session) -> None:
    """Seed one library with representative cleared + preserved rows.

    The single ``library`` row is itself part of the preserved boundary and survives;
    its songs/folders/tags/edges/pipeline-state/scan and ML rows are the cleared set.
    """
    lib_id = _seed_library(session)

    folder_id = _insert_pk(
        session,
        insert(LibraryFolder).values(library_id=lib_id, parent_id=None, path="/lifecycle/lib/album", name="album"),
    )
    song_id = _seed_song(session, lib_id, folder_id, "/lifecycle/lib/album/a.mp3")

    # Cleared: a tag, its song-tag edge, a canonical song-state + edge.
    tag_id = _insert_pk(session, insert(Tag).values(namespace="nom", name="artist", value="One"))
    session.execute(
        insert(SongTag).values(song_id=song_id, tag_id=tag_id, confidence=0.9, source="ml", created_at=1000)
    )
    state_id = _insert_pk(session, insert(SongState).values(name="processed", description=None))
    session.execute(insert(SongStateAssignment).values(song_id=song_id, state_id=state_id, created_at=1000))

    # Cleared: embeddings + an output stream for the cleared song.
    session.execute(
        text("INSERT INTO embeddings (song_id, backbone_id) VALUES (:song_id, :backbone_id)"),
        {"song_id": song_id, "backbone_id": "backbone-a"},
    )
    session.execute(
        insert(MlOutputStream).values(
            song_id=song_id,
            output_id="out_1",
            output_index=0,
            values=[0.1, 0.2, 0.3],
            created_at=1000,
        )
    )

    # Cleared: the library's pipeline state + scan record.
    session.execute(
        insert(PipelineState).values(
            library_id=lib_id, state_key="scan_state", state_data={"state": "idle"}, updated_at=1000
        )
    )
    session.execute(
        insert(LibraryScan).values(
            library_id=lib_id,
            scan_type="full",
            status="in_progress",
            started_at=1000,
            heartbeat_at=None,
            finished_at=None,
            files_found=0,
            files_processed=0,
            error=None,
        )
    )

    # Preserved: model registry, model output, calibration state.
    session.execute(
        insert(MlModel).values(
            id="model-suite-hash",
            model_type="classifier",
            backbone_id="backbone-a",
            enabled=1,
            created_at=1000,
            updated_at=1000,
            path=None,
            source="discovered",
        )
    )
    session.execute(
        insert(MlModelOutput).values(
            output_id="out_1",
            model_id="model-suite-hash",
            output_data={"label": "x"},
            created_at=1000,
            output_index=0,
            label=None,
            fully_labeled=0,
        )
    )
    session.execute(
        insert(CalibrationState).values(model_id="model-suite-hash", state_data={"cal": 1}, updated_at=1000)
    )

    # Preserved: worker health + claim.
    session.execute(insert(WorkerClaim).values(worker_id="w1", key="claim_1", value={"song": song_id}, claimed_at=1000))
    session.execute(insert(Health).values(worker_id="w1", status="healthy", last_seen=1000))

    # Preserved: an embedding-stream row referencing the cleared song (survives in
    # SQLite where FK cascades are not enforced; see module docstring nuance).
    session.execute(
        insert(MlEmbeddingStream).values(
            song_id=song_id,
            backbone_id="backbone-a",
            patches_emb=b"\x00\x01",
            created_at=1000,
        )
    )


@pytest.mark.unit
@pytest.mark.integration
class TestLibraryResetLifecycle:
    """A committed reset is durable: clear/preserve holds after engine close/reopen."""

    def test_reset_persists_across_close_and_reopen(self, tmp_path: Path) -> None:
        db_file = tmp_path / "lifecycle.db"

        # ── Phase 1: seed a fully populated world and commit it durably. ──
        engine_a = _build_engine(db_file)
        try:
            with Session(engine_a) as seed_session:
                _seed_lifecycle_world(seed_session)
                seed_session.commit()
                # Confirm the seeded rows exist before the reset.
                assert _count(seed_session, Library.__table__) == 1
                assert _count(seed_session, Song.__table__) == 1
                assert _count(seed_session, MlModel.__table__) == 1
        finally:
            engine_a.dispose()

        # ── Phase 2: reopen, run the maintenance reset, commit is repo-owned. ──
        engine_b = _build_engine(db_file)
        try:
            with Session(engine_b) as admin_session:
                maintenance = LibraryMaintenanceDb(LibraryResetRepo(cast("Any", admin_session)))
                maintenance.reset_library_data()
                # reset_library_data() performed its own commit; verify within-session.
                for name, table in _PRESERVED_TABLES.items():
                    assert _count(admin_session, table) > 0, f"preserved '{name}' missing pre-reopen"
        finally:
            engine_b.dispose()

        # ── Phase 3: reopen again (restart) and verify durability on disk. ──
        engine_c = _build_engine(db_file)
        try:
            with Session(engine_c) as reopened_session:
                cleared_models = {
                    "embeddings": Embedding.__table__,
                    "ml_output_streams": MlOutputStream.__table__,
                    "pipeline_states": PipelineState.__table__,
                    "song_tags": SongTag.__table__,
                    "song_state_assignments": SongStateAssignment.__table__,
                    "songs": Song.__table__,
                    "library_folders": LibraryFolder.__table__,
                    "tags": Tag.__table__,
                    "library_scans": LibraryScan.__table__,
                }
                for name, table in cleared_models.items():
                    assert _count(reopened_session, table) == 0, f"cleared '{name}' reappeared after reopen"
                for name, table in _PRESERVED_TABLES.items():
                    assert _count(reopened_session, table) == 1, f"preserved '{name}' did not survive reopen"
        finally:
            engine_c.dispose()
