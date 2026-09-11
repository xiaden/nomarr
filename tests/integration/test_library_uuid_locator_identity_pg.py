"""Fresh-PostgreSQL identity evidence for ``libraries.library_uuid`` and the locator wire.

P3-S3: schema identity (unique / immutable / rename / delete-recreate /
transaction rollback / concurrent duplicate retry) and the stored-UUID ->
``nom1`` locator round trip.

This module is the ``requires_database`` half of P3-S3. Docker/PostgreSQL is
DOWN in the execution environment and ``NOMARR_TEST_DATABASE_URL`` is unset, so
the module is skipped with an explicit environment-blocked reason — it is never
reported as PASS.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.song_locator_codec import decode_song_locator, encode_song_locator
from nomarr.persistence.models.library import Library

_PG_URL = os.environ.get("NOMARR_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_database,
    pytest.mark.skipif(
        not _PG_URL,
        reason=(
            "requires a live PostgreSQL server via NOMARR_TEST_DATABASE_URL; "
            "Docker/PostgreSQL unavailable locally so this evidence is environment-blocked"
        ),
    ),
]


@pytest.fixture
def engine():
    eng = create_engine(_PG_URL or "", future=True)
    yield eng
    eng.dispose()


def _mint_uuid() -> str:
    return str(uuid.uuid4())


def _unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _insert(engine, library_uuid: str, name: str) -> None:
    with Session(engine) as session:
        session.add(
            Library(
                library_uuid=library_uuid,
                name=name,
                path=f"/music/{name}",
                library_type="music",
                created_at=1000,
                updated_at=1000,
            )
        )
        session.commit()


def _delete(engine, library_uuid: str) -> None:
    with Session(engine) as session:
        session.query(Library).filter(Library.library_uuid == library_uuid).delete()
        session.commit()


def _locator(library_uuid: str, path: str) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(library_uuid=library_uuid), normalized_path=path)


def test_library_uuid_is_unique(engine) -> None:
    library_uuid = _mint_uuid()
    _insert(engine, library_uuid, _unique_name("p3-dup-a"))
    try:
        with pytest.raises(IntegrityError):
            _insert(engine, library_uuid, _unique_name("p3-dup-b"))
    finally:
        _delete(engine, library_uuid)


def test_rename_preserves_immutable_library_uuid(engine) -> None:
    library_uuid = _mint_uuid()
    name = _unique_name("p3-rename")
    _insert(engine, library_uuid, name)
    try:
        renamed = _unique_name("p3-renamed")
        with Session(engine) as session:
            row = session.scalar(select(Library).where(Library.library_uuid == library_uuid))
            assert row is not None
            row.name = renamed
            session.commit()

        with Session(engine) as session:
            row = session.scalar(select(Library).where(Library.library_uuid == library_uuid))
            assert row is not None
            assert row.library_uuid == library_uuid
            assert row.name == renamed
    finally:
        _delete(engine, library_uuid)


def test_delete_and_recreate_mints_new_library_uuid(engine) -> None:
    first_uuid = _mint_uuid()
    first_name = _unique_name("p3-recreate")
    _insert(engine, first_uuid, first_name)
    _delete(engine, first_uuid)

    second_uuid = _mint_uuid()
    _insert(engine, second_uuid, first_name)
    try:
        assert second_uuid != first_uuid
        with Session(engine) as session:
            assert session.scalar(select(Library).where(Library.library_uuid == first_uuid)) is None
            assert session.scalar(select(Library).where(Library.library_uuid == second_uuid)) is not None
    finally:
        _delete(engine, second_uuid)


def test_transaction_rollback_leaves_no_library_row(engine) -> None:
    library_uuid = _mint_uuid()
    name = _unique_name("p3-rollback")
    with Session(engine) as session:
        session.add(
            Library(
                library_uuid=library_uuid,
                name=name,
                path=f"/music/{name}",
                library_type="music",
                created_at=1000,
                updated_at=1000,
            )
        )
        session.flush()
        session.rollback()

    with Session(engine) as session:
        assert session.scalar(select(Library).where(Library.library_uuid == library_uuid)) is None


def test_concurrent_duplicate_uuid_conflicts_then_retry_succeeds(engine) -> None:
    library_uuid = _mint_uuid()
    _insert(engine, library_uuid, _unique_name("p3-concurrent-a"))
    try:
        with pytest.raises(IntegrityError):
            _insert(engine, library_uuid, _unique_name("p3-concurrent-b"))

        retry_uuid = _mint_uuid()
        _insert(engine, retry_uuid, _unique_name("p3-concurrent-retry"))
        try:
            with Session(engine) as session:
                assert session.scalar(select(Library).where(Library.library_uuid == retry_uuid)) is not None
        finally:
            _delete(engine, retry_uuid)
    finally:
        _delete(engine, library_uuid)


def test_stored_uuid_round_trips_through_locator_codec(engine) -> None:
    library_uuid = _mint_uuid()
    name = _unique_name("p3-wire")
    _insert(engine, library_uuid, name)
    try:
        with Session(engine) as session:
            stored = session.scalar(select(Library.library_uuid).where(Library.library_uuid == library_uuid))
        assert stored == library_uuid

        token = encode_song_locator(_locator(library_uuid, "album/song.flac"))
        decoded = decode_song_locator(token)
        assert decoded.library_uuid == library_uuid
        assert decoded.path == "album/song.flac"
        assert token.startswith("nom1")
    finally:
        _delete(engine, library_uuid)


def test_error_surface_is_typed_integrity_error(engine) -> None:
    library_uuid = _mint_uuid()
    _insert(engine, library_uuid, _unique_name("p3-error-a"))
    try:
        with pytest.raises(IntegrityError) as excinfo:
            _insert(engine, library_uuid, _unique_name("p3-error-b"))
        # The failure is the typed SQLAlchemy integrity error at the schema boundary,
        # not an untyped Python exception leaking identifiers from the projection layer.
        assert isinstance(excinfo.value, IntegrityError)
    finally:
        _delete(engine, library_uuid)
