"""Unit tests for the facade transaction contract removal (AR-SDR-4).

Verifies the shipped-state behavior of the persistence facades after the
transaction contract removal:

1. WRITE facade methods succeed WITHOUT a ``transaction()`` context; the
   ``transaction()`` context manager and the ``_require_transaction`` guard
   have been removed from every facade.
2. READ facade methods succeed without an explicit transaction (autobegin).
3. No facade (LibraryDb, AppDb, MlDb, or their sub-facades) exposes
   ``transaction()`` or ``_require_transaction``.

Facades are built with real SQLite sessions (so writes observe genuine
session state) and MagicMock repos (so writes delegate to mocks and never
touch real tables).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from nomarr.persistence.api.application import AppDb
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_regions import LibraryRegionsDb
from nomarr.persistence.api.library_scans import LibraryScansDb
from nomarr.persistence.api.library_songs import LibrarySongsDb
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.api.ml import MlDb


@pytest.fixture
def session() -> Session:
    """A real SQLite session so writes observe genuine session state."""
    engine = create_engine("sqlite://")
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _make_library(session: Session) -> tuple[LibraryDb, MagicMock]:
    """LibraryDb over a real session with mocked repos; returns the library repo mock."""
    library_repo = MagicMock()
    songs = LibrarySongsDb(
        session=session,
        song_repo=MagicMock(),
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
    )
    tags = LibraryTagsDb(session=session, tag_repo=MagicMock(), song_tag_repo=MagicMock())
    scans = LibraryScansDb(session=session, scan_repo=MagicMock())
    regions = LibraryRegionsDb(
        session=session,
        library_repo=library_repo,
        song_state_repo=MagicMock(),
    )
    db = LibraryDb(session=session, songs=songs, tags=tags, scans=scans, regions=regions)
    return db, library_repo


def _make_songs(session: Session) -> tuple[LibrarySongsDb, MagicMock]:
    song_repo = MagicMock()
    db = LibrarySongsDb(
        session=session,
        song_repo=song_repo,
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
    )
    return db, song_repo


def _make_app(session: Session) -> AppDb:
    return AppDb(
        session=session,
        app_repo=MagicMock(),
        library_repo=MagicMock(),
        song_state_repo=MagicMock(),
        pipeline_repo=MagicMock(),
    )


def _make_ml(session: Session) -> MlDb:
    return MlDb(
        session=session,
        vector_repo=MagicMock(),
        model_repo=MagicMock(),
        output_repo=MagicMock(),
        calibration_repo=MagicMock(),
        embedding_stream_repo=MagicMock(),
    )


# ── (1) Facades expose no transaction() or _require_transaction ─────────────


def test_facades_do_not_expose_transaction(session: Session) -> None:
    db, _ = _make_library(session)
    app_db = _make_app(session)
    ml_db = _make_ml(session)

    for facade in (db, db.songs, db.tags, db.scans, db.regions, app_db, ml_db):
        assert not hasattr(facade, "transaction"), f"{type(facade).__name__} must not expose transaction() (AR-SDR-4)."
        assert not hasattr(facade, "_require_transaction"), (
            f"{type(facade).__name__} must not expose _require_transaction (AR-SDR-4)."
        )


# ── (2) WRITE methods succeed without transaction() ─────────────────────────


def test_write_succeeds_without_transaction(session: Session) -> None:
    db, library_repo = _make_library(session)
    db.regions.add_library({"name": "music"})
    library_repo.add_library.assert_called_once_with({"name": "music"})


def test_write_via_forwarder_succeeds_without_transaction(session: Session) -> None:
    db, library_repo = _make_library(session)
    db.add_library({"name": "music"})
    library_repo.add_library.assert_called_once_with({"name": "music"})


def test_sub_facade_write_succeeds_without_transaction(session: Session) -> None:
    songs, song_repo = _make_songs(session)
    songs.remove_song(1)
    song_repo.delete_song.assert_called_once_with(1)


def test_app_db_write_succeeds_without_transaction(session: Session) -> None:
    app_db = _make_app(session)
    app_db.update_config_option("config_scan_interval", {"value": 60})
    app_db._app_repo.upsert_meta.assert_called_once_with("config_scan_interval", {"value": 60})


def test_ml_db_write_succeeds_without_transaction(session: Session) -> None:
    ml_db = _make_ml(session)
    ml_db.add_model({"model_id": "m1"})
    ml_db._model_repo.upsert_model.assert_called_once_with({"model_id": "m1"})


# ── (3) READ methods succeed without transaction() (autobegin) ──────────────


def test_read_without_transaction_succeeds(session: Session) -> None:
    db, library_repo = _make_library(session)
    library_repo.get_library.return_value = {"id": 1, "name": "music"}
    assert db.get_library(1) == {"id": 1, "name": "music"}
    library_repo.get_library.assert_called_once_with(1)


def test_read_methods_are_not_guarded(session: Session) -> None:
    app_db = _make_app(session)
    ml_db = _make_ml(session)
    # Reads exercise autobegin on a real session without raising.
    app_db._app_repo.get_vram_promises.return_value = []
    assert app_db.list_vram_promises() == []
    assert ml_db.list_models() is not None


# ── (4) Boot-path smoke test: Application.start() write sequence ────────────


def test_boot_path_write_sequence_succeeds(session: Session) -> None:
    """The Application.start() sequence of write calls must succeed without
    any transaction() wrapper (AR-SDR-4).

    Mirrors nomarr/app.py start(): truncate_health() -> update_health()
    and migration_runner_comp's db.set_version() (update_config_option).
    """
    app_db = _make_app(session)
    app_db.truncate_health()
    app_db.update_health("app", {"status": "starting"})
    app_db.update_config_option("version", {"value": "001"})
    app_db._app_repo.truncate_health.assert_called_once()
