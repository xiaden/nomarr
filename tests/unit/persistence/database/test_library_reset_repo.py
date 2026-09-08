"""Unit tests for the all-or-nothing LibraryResetRepo aggregate.

The shared repository-test ``pg_session`` fixture builds a SQLite engine that
excludes the ``embeddings`` table (HALFVEC/pgvector columns cannot compile for
SQLite — see ``tests/unit/persistence/database/conftest.py``). The reset
aggregate clears ``embeddings`` with a table-wide DELETE, so these tests
materialise a minimal SQLite-compatible ``embeddings`` table (id/song_id/
backbone_id) that the aggregate's delete operates on. Vector contents are
irrelevant to reset correctness — only row presence/absence matters — so this
faithfully exercises the aggregate's clear + preserve boundary and its
rollback choreography without needing a real pgvector server.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import func, insert, select, text

from nomarr.persistence.database.library_reset_repo import LibraryResetRepo
from nomarr.persistence.models.calibration_history import CalibrationHistory
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
    from sqlalchemy.orm import Session

_LIBRARY_NAMES = count(1)

# Minimal SQLite-compatible stand-in for the pgvector ``embeddings`` table.
_EMBEDDINGS_DDL = """
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER NOT NULL,
    backbone_id VARCHAR(100) NOT NULL
)
"""

# Tables the reset must fully clear.
_CLEARED_TABLES = {
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

# Tables the reset must leave untouched (boundary preservation).
_PRESERVED_TABLES = {
    "libraries": Library.__table__,
    "ml_models": MlModel.__table__,
    "ml_model_outputs": MlModelOutput.__table__,
    "calibration_states": CalibrationState.__table__,
    "calibration_history": CalibrationHistory.__table__,
    "worker_health": Health.__table__,
    "worker_claims": WorkerClaim.__table__,
    "song_states": SongState.__table__,
    "ml_embedding_streams": MlEmbeddingStream.__table__,
}


@pytest.fixture
def embeddings_table(pg_engine) -> None:
    """Ensure the SQLite ``embeddings`` table exists for the aggregate delete."""
    with pg_engine.begin() as conn:
        conn.execute(text(_EMBEDDINGS_DDL))


def _count(session: Session, table) -> int:
    """Return the current row count of *table*."""
    return int(session.execute(select(func.count()).select_from(table)).scalar_one())


def _insert_pk(session: Session, stmt) -> int:
    """Execute an INSERT and return its autoincrement primary key."""
    result = session.execute(stmt)
    return int(cast("Any", result).inserted_primary_key[0])


def _seed_library(session: Session, path: str = "/reset/lib") -> int:
    return _insert_pk(
        session,
        insert(Library).values(
            name=f"Reset Lib {next(_LIBRARY_NAMES)}",
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


def _seed_state(session: Session, library_id: int, state_key: str) -> None:
    session.execute(
        insert(PipelineState).values(
            library_id=library_id,
            state_key=state_key,
            state_data={"state": "idle"},
            updated_at=1000,
        )
    )


def _seed_scan(session: Session, library_id: int, *, status: str = "in_progress") -> None:
    session.execute(
        insert(LibraryScan).values(
            library_id=library_id,
            scan_type="full",
            status=status,
            started_at=1000,
            heartbeat_at=None,
            finished_at=None,
            files_found=0,
            files_processed=0,
            error=None,
        )
    )


def _seed_embedding(session: Session, song_id: int, backbone_id: str) -> None:
    session.execute(
        text("INSERT INTO embeddings (song_id, backbone_id) VALUES (:song_id, :backbone_id)"),
        {"song_id": song_id, "backbone_id": backbone_id},
    )


def _seed_full_world(session: Session) -> tuple[int, int]:
    """Seed a library with songs, folders, ML data, state/tags, and scans.

    Also seeds a second *empty* library (no songs) that still carries
    pipeline-state and scan rows. Returns ``(populated_library_id,
    empty_library_id)``.
    """
    lib_id = _seed_library(session)

    parent_id = _insert_pk(
        session,
        insert(LibraryFolder).values(library_id=lib_id, parent_id=None, path="/reset/lib/album", name="album"),
    )
    child_id = _insert_pk(
        session,
        insert(LibraryFolder).values(
            library_id=lib_id,
            parent_id=parent_id,
            path="/reset/lib/album/disc1",
            name="disc1",
        ),
    )

    song_a = _seed_song(session, lib_id, child_id, "/reset/lib/album/disc1/a.mp3")
    song_b = _seed_song(session, lib_id, None, "/reset/lib/b.mp3")

    # Two tags, assigned to songs A and B respectively.
    tag_a = _insert_pk(session, insert(Tag).values(namespace="nom", name="artist", value="One"))
    tag_b = _insert_pk(session, insert(Tag).values(namespace="nom", name="artist", value="Two"))
    session.execute(insert(SongTag).values(song_id=song_a, tag_id=tag_a, confidence=0.9, source="ml", created_at=1000))
    session.execute(insert(SongTag).values(song_id=song_b, tag_id=tag_b, confidence=0.8, source="ml", created_at=1000))

    # One canonical song-state row (preserved) plus edges for both songs.
    state_id = _insert_pk(session, insert(SongState).values(name="processed", description=None))
    session.execute(insert(SongStateAssignment).values(song_id=song_a, state_id=state_id, created_at=1000))
    session.execute(insert(SongStateAssignment).values(song_id=song_b, state_id=state_id, created_at=1000))

    # Multiple backbones across songs (embedding cardinality per song/backbone).
    _seed_embedding(session, song_a, "backbone-a")
    _seed_embedding(session, song_a, "backbone-b")
    _seed_embedding(session, song_b, "backbone-a")

    # Output streams: two for song A, one for song B (multi-row single delete).
    for idx, out_id in enumerate(["out_1", "out_2"]):
        session.execute(
            insert(MlOutputStream).values(
                song_id=song_a,
                output_id=out_id,
                output_index=idx,
                values=[0.1, 0.2, 0.3],
                created_at=1000,
            )
        )
    session.execute(
        insert(MlOutputStream).values(
            song_id=song_b,
            output_id="out_3",
            output_index=0,
            values=[0.4, 0.5],
            created_at=1000,
        )
    )

    # Pipeline-state + scan rows for the populated library.
    _seed_state(session, lib_id, "scan_state")
    _seed_state(session, lib_id, "ml_state")
    _seed_scan(session, lib_id)

    # Preserved ML registry, calibration, health, and claims rows.
    session.execute(
        insert(MlModel).values(
            id="model-suite-hash",
            model_type="classifier",
            backbone_id="backbone-a",
            enabled=1,
            created_at=1000,
            updated_at=1000,
            path=None,
            backbone=None,
            head_type=None,
            model_stem=None,
            output_count=1,
            fully_configured=0,
            is_known=0,
            source="discovered",
            head_release_date=None,
            embedder_release_date=None,
            registered_at=None,
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
    session.execute(
        insert(CalibrationHistory).values(
            model_id="model-suite-hash", event="recalibrated", data={"k": 1}, created_at=1000
        )
    )
    session.execute(insert(WorkerClaim).values(worker_id="w1", key="claim_1", value={"song": song_a}, claimed_at=1000))
    session.execute(insert(Health).values(worker_id="w1", status="healthy", last_seen=1000))

    # Embedding stream row referencing a song that will be cleared. This table
    # is part of the preserved boundary (never targeted by the reset); see the
    # WARNING in the final report about the physical ON DELETE CASCADE nuance.
    session.execute(
        insert(MlEmbeddingStream).values(
            song_id=song_a,
            backbone_id="backbone-a",
            patches_emb=b"\x00\x01",
            created_at=1000,
        )
    )

    # Empty library (no songs) that still owns pipeline-state + scan rows.
    empty_lib_id = _seed_library(session, "/reset/empty")
    _seed_state(session, empty_lib_id, "scan_state")
    _seed_scan(session, empty_lib_id, status="pending")

    return lib_id, empty_lib_id


@pytest.mark.unit
class TestLibraryResetRepoSignature:
    """The aggregate surface exposes no caller-owned storage identifiers."""

    def test_reset_method_takes_no_storage_identifiers(self) -> None:
        """reset_library_data must not accept collections, songs, or library ids."""
        import inspect

        params = inspect.signature(LibraryResetRepo.reset_library_data).parameters
        # Only ``self`` — no caller-supplied session/collections/song/library ids.
        assert list(params) == ["self"]

    def test_reset_returns_none(self, pg_session, embeddings_table) -> None:
        """The reset surface is typed None — no partial-success payload."""
        _seed_full_world(pg_session)
        LibraryResetRepo(pg_session).reset_library_data()
        # ``from __future__ import annotations`` stores the annotation as the string 'None'.
        assert LibraryResetRepo.reset_library_data.__annotations__["return"] == "None"
        # Reset performed a full clear rather than returning a partial payload.
        assert _count(pg_session, Song.__table__) == 0


@pytest.mark.unit
@pytest.mark.integration
class TestLibraryResetRepoReset:
    """End-to-end clear/preserve boundary of the atomic reset aggregate."""

    def test_successful_reset_clears_targets_and_preserves_boundary(self, pg_session, embeddings_table) -> None:
        """Full reset clears every target table and preserves every boundary table."""
        _seed_full_world(pg_session)
        before = {name: _count(pg_session, tbl) for name, tbl in _PRESERVED_TABLES.items()}

        repo = LibraryResetRepo(pg_session)
        repo.reset_library_data()

        for name, tbl in _CLEARED_TABLES.items():
            assert _count(pg_session, tbl) == 0, f"table '{name}' was not cleared"
        for name, count_before in before.items():
            assert _count(pg_session, _PRESERVED_TABLES[name]) == count_before, (
                f"preserved table '{name}' lost rows during reset"
            )

    def test_empty_library_pipeline_state_and_scans_removed(self, pg_session, embeddings_table) -> None:
        """A library with no songs still loses its pipeline-state and scan rows."""
        empty_lib_id = _seed_library(pg_session, "/reset/empty-only")
        _seed_state(pg_session, empty_lib_id, "scan_state")
        _seed_scan(pg_session, empty_lib_id)

        repo = LibraryResetRepo(pg_session)
        repo.reset_library_data()

        # The library itself survives the reset...
        assert _count(pg_session, Library.__table__) == 1
        # ...but its pipeline state and scan records do not.
        assert _count(pg_session, PipelineState.__table__) == 0
        assert _count(pg_session, LibraryScan.__table__) == 0

    def test_reset_is_idempotent(self, pg_session, embeddings_table) -> None:
        """Calling reset twice leaves the boundary intact and tables clear."""
        _seed_full_world(pg_session)
        repo = LibraryResetRepo(pg_session)
        repo.reset_library_data()
        repo.reset_library_data()

        for tbl in _CLEARED_TABLES.values():
            assert _count(pg_session, tbl) == 0
        assert _count(pg_session, Library.__table__) == 2


@pytest.mark.unit
@pytest.mark.integration
class TestLibraryResetRepoAtomicity:
    """Mid-operation failures roll the whole reset back — no partial success."""

    def test_failure_rolls_back_earlier_deletes(self, pg_session, embeddings_table, monkeypatch) -> None:
        """An injected failure after several clears undoes every earlier delete."""
        _seed_full_world(pg_session)
        repo = LibraryResetRepo(pg_session)

        def _boom(self) -> None:
            raise RuntimeError("injected mid-reset failure")

        # The last statement in the aggregate (tags) is the injection seam.
        monkeypatch.setattr(LibraryResetRepo, "_delete_tags", _boom)

        with pytest.raises(RuntimeError, match="injected mid-reset failure"):
            repo.reset_library_data()

        # Nothing was partially applied: every target table still holds its rows.
        for name, tbl in _CLEARED_TABLES.items():
            assert _count(pg_session, tbl) > 0, f"table '{name}' lost rows after a failed reset (partial success)"
        # Preserved rows likewise untouched.
        for tbl in _PRESERVED_TABLES.values():
            assert _count(pg_session, tbl) > 0

    def test_failure_preserves_exception_mapping(self, pg_session, embeddings_table, monkeypatch) -> None:
        """A mid-operation failure re-raises the original exception unchanged."""
        _seed_full_world(pg_session)
        repo = LibraryResetRepo(pg_session)

        def _boom(self) -> None:
            raise RuntimeError("distinct-failure")

        monkeypatch.setattr(LibraryResetRepo, "_delete_tags", _boom)
        with pytest.raises(RuntimeError, match="distinct-failure"):
            repo.reset_library_data()

    def test_session_usable_after_failure(self, pg_session, embeddings_table, monkeypatch) -> None:
        """After a failed reset the session remains usable for a clean retry."""
        _seed_full_world(pg_session)
        repo = LibraryResetRepo(pg_session)

        def _boom(self) -> None:
            raise RuntimeError("injected")

        monkeypatch.setattr(LibraryResetRepo, "_delete_tags", _boom)
        with pytest.raises(RuntimeError):
            repo.reset_library_data()

        monkeypatch.undo()
        # A clean retry now succeeds and commits the full clear.
        repo.reset_library_data()
        for tbl in _CLEARED_TABLES.values():
            assert _count(pg_session, tbl) == 0
