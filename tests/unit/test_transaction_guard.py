"""Unit tests for the facade transaction guard (AR-2).

Verifies the five Phase-1 behaviors of ``transaction()`` and the write-method
guard on the persistence facades:

1. a WRITE method called without ``transaction()`` raises ``FacadeMisuseError``;
2. a WRITE method called inside ``with facade.transaction():`` succeeds;
3. a READ method called without ``transaction()`` succeeds (autobegin);
4. entering ``transaction()`` after a READ warns but does not error;
5. nested ``transaction()`` calls warn.

Facades are built with real SQLite sessions (so the guard observes genuine
session transaction state) and MagicMock repos (so writes delegate to mocks
and never touch real tables).
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from nomarr.helpers.exceptions import FacadeMisuseError
from nomarr.persistence.api.application import AppDb
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_files import LibraryFilesDb
from nomarr.persistence.api.library_regions import LibraryRegionsDb
from nomarr.persistence.api.library_scans import LibraryScansDb
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.api.ml import MlDb

WARN_MESSAGE = "Transaction already active"


@pytest.fixture
def session() -> Session:
    """A real SQLite session so the guard sees genuine session state."""
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
    files = LibraryFilesDb(
        session=session,
        file_repo=MagicMock(),
        folder_repo=MagicMock(),
        file_state_repo=MagicMock(),
    )
    tags = LibraryTagsDb(session=session, tag_repo=MagicMock(), file_tag_repo=MagicMock())
    scans = LibraryScansDb(session=session, scan_repo=MagicMock())
    regions = LibraryRegionsDb(
        session=session,
        library_repo=library_repo,
        file_state_repo=MagicMock(),
        pipeline_repo=MagicMock(),
    )
    db = LibraryDb(session=session, files=files, tags=tags, scans=scans, regions=regions)
    return db, library_repo


def _make_files(session: Session) -> tuple[LibraryFilesDb, MagicMock]:
    file_repo = MagicMock()
    db = LibraryFilesDb(
        session=session,
        file_repo=file_repo,
        folder_repo=MagicMock(),
        file_state_repo=MagicMock(),
    )
    return db, file_repo


def _make_app(session: Session) -> AppDb:
    return AppDb(
        session=session,
        app_repo=MagicMock(),
        library_repo=MagicMock(),
        navidrome_repo=MagicMock(),
        file_state_repo=MagicMock(),
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


# ── (1) WRITE without transaction() raises FacadeMisuseError ────────────────


def test_write_without_transaction_raises(session: Session) -> None:
    db, _ = _make_library(session)
    with pytest.raises(FacadeMisuseError, match="write method"):
        db.regions.add_library({"name": "music"})


def test_write_via_forwarder_without_transaction_raises(session: Session) -> None:
    db, _ = _make_library(session)
    with pytest.raises(FacadeMisuseError, match="write method"):
        db.add_library({"name": "music"})


def test_sub_facade_write_without_transaction_raises(session: Session) -> None:
    files, _ = _make_files(session)
    with pytest.raises(FacadeMisuseError, match="write method"):
        files.remove_file(1)


def test_app_db_write_without_transaction_raises(session: Session) -> None:
    app_db = _make_app(session)
    with pytest.raises(FacadeMisuseError, match="write method"):
        app_db.update_config_option("config_scan_interval", {"value": 60})


def test_ml_db_write_without_transaction_raises(session: Session) -> None:
    ml_db = _make_ml(session)
    with pytest.raises(FacadeMisuseError, match="write method"):
        ml_db.add_model({"model_id": "m1"})


# ── (2) WRITE inside transaction() succeeds ─────────────────────────────────


def test_write_inside_library_transaction_succeeds(session: Session) -> None:
    db, library_repo = _make_library(session)
    with db.transaction():
        db.regions.add_library({"name": "music"})
    library_repo.add_library.assert_called_once_with({"name": "music"})


def test_sub_facade_write_inside_transaction_succeeds(session: Session) -> None:
    files, file_repo = _make_files(session)
    db, _ = _make_library(session)
    with db.transaction():
        files.remove_file(7)
    file_repo.delete_file.assert_called_once_with(7)


def test_app_db_write_inside_transaction_succeeds(session: Session) -> None:
    app_db = _make_app(session)
    with app_db.transaction():
        app_db.update_config_option("config_scan_interval", {"value": 60})
    app_db._app_repo.upsert_meta.assert_called_once_with("config_scan_interval", {"value": 60})


def test_ml_db_write_inside_transaction_succeeds(session: Session) -> None:
    ml_db = _make_ml(session)
    with ml_db.transaction():
        ml_db.add_model({"model_id": "m1"})
    ml_db._model_repo.upsert_model.assert_called_once_with({"model_id": "m1"})


# ── (3) READ without transaction() succeeds (autobegin) ─────────────────────


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


# ── (4) transaction() after a READ warns but does not error ─────────────────


def test_transaction_after_read_warns_but_does_not_error(session: Session) -> None:
    db, library_repo = _make_library(session)
    # A genuine DB read autobegins a read-only transaction on the real session.
    # (The MagicMock repos do not execute SQL, so simulate the read directly.)
    session.execute(text("SELECT 1"))
    assert session.in_transaction()
    with pytest.warns(UserWarning, match=WARN_MESSAGE), db.transaction():
        db.regions.add_library({"name": "music"})
    library_repo.add_library.assert_called_once_with({"name": "music"})


def test_transaction_without_prior_read_does_not_warn(session: Session) -> None:
    db, _ = _make_library(session)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with db.transaction():
            db.regions.add_library({"name": "music"})


# ── (5) nested transaction() calls warn ─────────────────────────────────────


def test_nested_transaction_warns(session: Session) -> None:
    db, library_repo = _make_library(session)
    with db.transaction(), pytest.warns(UserWarning, match=WARN_MESSAGE), db.transaction():
        db.regions.add_library({"name": "music"})
    library_repo.add_library.assert_called_once_with({"name": "music"})


# ── (6) Boot-path smoke test: Application.start() write sequence ─────────────


def test_boot_path_write_sequence_succeeds(session: Session) -> None:
    """Invert the QA Round 1 boot crash: the Application.start() sequence of
    per-write ``transaction()`` blocks must NOT raise FacadeMisuseError.

    Mirrors nomarr/app.py start(): truncate_health() -> update_health()
    and migration_runner_comp's db.set_version() (update_config_option).
    Each guarded write is wrapped in its OWN per-write transaction block
    (repos commit internally, so a multi-write block would raise).
    """
    app_db = _make_app(session)
    with app_db.transaction():
        app_db.truncate_health()
    with app_db.transaction():
        app_db.update_health("app", {"status": "starting"})
    with app_db.transaction():
        app_db.update_config_option("version", {"value": "001"})
    app_db._app_repo.truncate_health.assert_called_once()


def test_unwrapped_write_still_raises_after_boot_sequence(session: Session) -> None:
    """The guard must remain intact: an unwrapped guarded write still raises."""
    app_db = _make_app(session)
    with app_db.transaction():
        app_db.truncate_health()
    with pytest.raises(FacadeMisuseError, match="write method"):
        app_db.update_health("app", {"status": "starting"})
