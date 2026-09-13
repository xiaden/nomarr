"""Shared fixtures and helpers for characterization tests.

Provides:
- Session-scoped PostgreSQL container via testcontainers
- Alembic migration runner against the test database
- Database instance with seed data factory
- Result normalizer and serializer for snapshot comparisons
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.db import Database

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"

# Postgres image with pgvector support
POSTGRES_IMAGE = "pgvector/pgvector:pg17"
POSTGRES_USER = "nomarr"
POSTGRES_PASSWORD = "nomarr"
POSTGRES_DB = "nomarr_test"


# ---------------------------------------------------------------------------
# Session-scoped fixtures: container + database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def postgres_container():
    """Start a PostgreSQL container with pgvector support.

    The container lives for the entire test session to avoid the overhead
    of starting/stopping per test.
    """
    with PostgresContainer(
        image=POSTGRES_IMAGE,
        username=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
        port=5432,
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def test_db_url(request) -> str:
    """Build the SQLAlchemy URL for the test database.

    Uses psycopg2 (sync driver) for Alembic migrations and Database facade.

    When ``NOMARR_TEST_DATABASE_URL`` is set, that already-running native
    PostgreSQL/pgvector database is used instead of starting a testcontainer.
    This additive fast path lets a workspace with a local pgvector cluster run
    the ``requires_database`` evidence without Docker; CI (no override set)
    still uses the ``pgvector/pgvector:pg17`` testcontainer unchanged.
    """
    override = os.environ.get("NOMARR_TEST_DATABASE_URL")
    if override:
        return override
    pg = request.getfixturevalue("postgres_container")
    return (
        f"postgresql+psycopg2://{pg.username}:{pg.password}"
        f"@{pg.get_container_host_ip()}:{pg.get_exposed_port(pg.port)}/{pg.dbname}"
    )


@pytest.fixture(scope="session")
def run_alembic_migrations(test_db_url) -> Generator[str, None, None]:
    """Run Alembic migrations against the test database.

    Executes once per session after the container is up.
    """
    alembic_cfg = AlembicConfig(str(ALEMBIC_INI))
    # Override the database URL from the test container
    alembic_cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(alembic_cfg, "head")
    yield test_db_url


@pytest.fixture(scope="session")
def db(run_alembic_migrations) -> Generator[Database, None, None]:
    """Create a Database instance connected to the test database.

    The Database instance is shared across all tests in the session.
    Tests should use the seed_data fixture to populate test data.
    """
    database = Database(url=run_alembic_migrations, echo=False, pool_size=2, max_overflow=5)
    yield database
    database.close()


@pytest.fixture(scope="session")
def pg_engine(run_alembic_migrations):
    """Session-scoped synchronous SQLAlchemy engine on the real migrated PostgreSQL.

    Unlike the SQLite ``pg_engine`` in ``tests/unit/persistence/database/conftest.py``,
    this engine targets the live pgvector:pg17 container and so can run the ML
    inference aggregate, whose ``embeddings`` table uses a PostgreSQL-only
    ``HALFVEC`` column. Schema is provided by the already-run Alembic migrations.
    """
    engine = create_engine(run_alembic_migrations, echo=False)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def inference_session(pg_engine):
    """Per-test transactional session on the real PostgreSQL container.

    Mirrors the ``pg_session`` fixture used by SQLite repository tests (a
    connection-bound SAVEPOINT session that rolls back at the end of every test)
    but on the real pgvector database, so the ML write aggregate and its
    ``(song, backbone)``-scoped replacement and rollback semantics can be
    exercised against the true ``embeddings`` table. After each test the outer
    transaction rolls back, leaving no residue.
    """
    engine = pg_engine
    conn = engine.connect()
    conn.begin()
    conn.begin_nested()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# Function-scoped fixtures: seed data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_data(db):
    """Insert seed data into the test database using the sealed domain facade.

    Seed creation goes through the canonical typed domain contracts —
    ``create_library(Library)``, ``add_songs_to_library_batch(SongUpsertInput, …)``,
    ``ensure_tag(TagRef)``, ``replace_song_tags(SongIdentity, …)`` and
    ``start_scan(Library, …)``. The returned song identities are semantic
    ``SongIdentity`` locators; semantic identities are constructed
    directly (no integer-handle resolver crossing) and exposed under
    ``song_identities``.

    Creates:
    - 2 libraries
    - 3 songs (2 in library 1, 1 in library 2)
    - 5 tags
    - 1 scan record for library 1

    Returns a dict with the created domain values for use in tests.
    """
    # Clean up any existing data first (idempotent)
    _cleanup_seed_data(db)

    created: dict[str, list[object]] = {
        "libraries": [],
        "songs": [],
        "song_identities": [],
        "tags": [],
        "scans": [],
    }

    # Create 2 libraries (domain values)
    lib1 = db.library.create_library(Library(name="TestLib1", root_path="/tmp/test1"))
    lib2 = db.library.create_library(Library(name="TestLib2", root_path="/tmp/test2"))
    created["libraries"] = [lib1, lib2]

    # Create 3 songs (2 in lib1, 1 in lib2) through the canonical typed
    # SongUpsert batch owner. The returned values are locator-shaped identities;
    # generated persistence IDs remain private to the repository.
    now_ms_val = now_ms()
    song_identities = list(
        db.library.add_songs_to_library_batch(
            [
                SongUpsertInput(
                    library=LibraryIdentity(
                        library_uuid=lib1.library_uuid or "", name=lib1.name, root_path=lib1.root_path
                    ),
                    path="/tmp/test1/song1.flac",
                    scan=SongScanUpdate(
                        normalized_path="song1.flac",
                        file_size=1024000,
                        modified_time=now_ms_val.value,
                        duration_seconds=180.5,
                    ),
                ),
                SongUpsertInput(
                    library=LibraryIdentity(
                        library_uuid=lib1.library_uuid or "", name=lib1.name, root_path=lib1.root_path
                    ),
                    path="/tmp/test1/song2.mp3",
                    scan=SongScanUpdate(
                        normalized_path="song2.mp3",
                        file_size=512000,
                        modified_time=now_ms_val.value,
                        duration_seconds=240.0,
                    ),
                ),
            ]
        )
    )
    song_identities.extend(
        db.library.add_songs_to_library_batch(
            [
                SongUpsertInput(
                    library=LibraryIdentity(
                        library_uuid=lib2.library_uuid or "", name=lib2.name, root_path=lib2.root_path
                    ),
                    path="/tmp/test2/song3.flac",
                    scan=SongScanUpdate(
                        normalized_path="song3.flac",
                        file_size=2048000,
                        modified_time=now_ms_val.value,
                        duration_seconds=300.0,
                    ),
                )
            ]
        )
    )
    created["songs"] = song_identities
    created["song_identities"] = song_identities

    # Create 5 tags via the domain identity (never a storage id).
    tag1 = db.library.ensure_tag(TagRef(name="nom:mood-strict", value="happy", namespace="nom"))
    tag2 = db.library.ensure_tag(TagRef(name="nom:mood-strict", value="sad", namespace="nom"))
    tag3 = db.library.ensure_tag(TagRef(name="nom:genre", value="rock", namespace="nom"))
    tag4 = db.library.ensure_tag(TagRef(name="nom:genre", value="jazz", namespace="nom"))
    tag5 = db.library.ensure_tag(TagRef(name="nom:tempo", value="fast", namespace="nom"))
    created["tags"] = [tag1, tag2, tag3, tag4, tag5]

    # Assign tags to songs via directly-constructed semantic locators: no
    # integer-handle -> SongIdentity resolver crossing participates.
    assert lib1.library_uuid is not None
    assert lib2.library_uuid is not None
    song1 = SongIdentity(
        library=LibraryIdentity(library_uuid=lib1.library_uuid),
        normalized_path="song1.flac",
    )
    song2 = SongIdentity(
        library=LibraryIdentity(library_uuid=lib1.library_uuid),
        normalized_path="song2.mp3",
    )
    song3 = SongIdentity(
        library=LibraryIdentity(library_uuid=lib2.library_uuid),
        normalized_path="song3.flac",
    )
    created["song_identities"] = [song1, song2, song3]
    created["songs"] = [song1, song2, song3]
    db.library.replace_song_tags(
        song1,
        [
            SongTagAssignment(name="nom:mood-strict", value="happy", namespace="nom", confidence=0.95, source="ml"),
            SongTagAssignment(name="nom:genre", value="rock", namespace="nom", confidence=0.88, source="ml"),
        ],
    )
    db.library.replace_song_tags(
        song2,
        [
            SongTagAssignment(name="nom:mood-strict", value="sad", namespace="nom", confidence=0.72, source="ml"),
        ],
    )

    # Create 1 scan record for library 1 via start_scan.
    scan = db.library.start_scan(lib1, scan_type="full", started_at=now_ms_val.value - 60000)
    created["scans"] = [scan]

    yield created

    # Cleanup after test
    _cleanup_seed_data(db)


def _cleanup_seed_data(db: Database) -> None:
    """Remove all seed data from the database via the sealed domain facade.

    Called before and after each test to ensure isolation. Removes libraries
    (cascades to songs, folders, and scans), then cleans up orphaned tags.
    """
    try:
        for lib in db.library.list_libraries():
            db.library.remove_library(lib)
        db.library.admin_cleanup_orphaned_tags()
    except Exception:
        # If cleanup fails, continue (test database will be recreated)
        pass


# ---------------------------------------------------------------------------
# Result normalization (P1-S2)
# ---------------------------------------------------------------------------

# ``libraries.library_uuid`` is minted randomly per library row, so bare canonical
# version-4 UUID strings are masked to keep locator/UUID-bearing snapshots
# deterministic across runs.
_CANONICAL_UUID4_RE = re.compile("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

# Opaque SongLocator wire token prefix (``nomarr.helpers.song_locator_codec``).
_SONG_LOCATOR_PREFIX = "nom1"

# pytest's ``tmp_path`` embeds a per-invocation run counter inside an otherwise
# identical absolute path; mask the counter so path-bearing snapshots are
# deterministic.
_PYTEST_TMP_RE = re.compile(r"pytest-\d+")


def _mask_song_locator(token: str) -> str:
    """Mask the random ``library_uuid`` embedded in an opaque ``nom1`` token.

    Decodes the canonical payload, replaces ``library_uuid`` with the stable
    ``"<UUID>"`` placeholder, and re-encodes deterministically. The relative
    ``path`` is preserved, so locators remain distinguishable **only when**
    their relative path differs; two locators that share a path but differ only
    by ``library_uuid`` collapse to the same masked token. Malformed payloads
    fail to decode; payloads that decode but are not exactly
    ``{library_uuid, path}`` are rejected — both fall back to a single stable
    ``"<SONG_LOCATOR>"`` placeholder, which also drops the ``nom1`` prefix.
    """
    body = token[len(_SONG_LOCATOR_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return "<SONG_LOCATOR>"
    if not isinstance(payload, dict) or set(payload) != {"library_uuid", "path"}:
        return "<SONG_LOCATOR>"
    payload["library_uuid"] = "<UUID>"
    masked = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _SONG_LOCATOR_PREFIX + base64.urlsafe_b64encode(masked).decode("ascii").rstrip("=")


def _normalize(value: Any) -> Any:
    """Normalize a value for snapshot comparison.

    Applies the following transformations recursively:
    - DB IDs (integers > 1000) → "<DB_ID>"
    - Canonical version-4 UUID strings → "<UUID>"
    - ``nom1`` SongLocator tokens → deterministic token with masked UUID
    - pytest ``tmp_path`` run counters (``pytest-<n>``) → ``pytest-<N>``
    - Floats → rounded to 6 decimal places
    - numpy ndarray → .tolist()
    - dataclasses → dict (so their field values are normalized too)
    - dict, list, tuple → recursively normalized
    - Other types → passed through (orjson handles datetime, UUID, Enum)

    Args:
        value: The value to normalize.

    Returns:
        The normalized value.
    """
    # Handle numpy arrays first
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            value = value.tolist()
    except ImportError:
        pass

    # Mask strings carrying per-run identity before generic pass-through.
    if isinstance(value, str):
        if _CANONICAL_UUID4_RE.fullmatch(value):
            return "<UUID>"
        if value.startswith(_SONG_LOCATOR_PREFIX) and len(value) > len(_SONG_LOCATOR_PREFIX):
            return _mask_song_locator(value)
        if "pytest-" in value:
            return _PYTEST_TMP_RE.sub("pytest-<N>", value)
        return value

    # DB ID masking: integers > 1000 are likely database IDs
    if isinstance(value, int) and not isinstance(value, bool) and value > 1000:
        return "<DB_ID>"

    # Float rounding: 6 decimal places
    if isinstance(value, float):
        return round(value, 6)

    # Dataclasses bypass container recursion above, so expose their fields to
    # normalization (asdict yields plain dicts/lists recursively).
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalize(dataclasses.asdict(value))

    # Recursive normalization for containers
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item) for item in value)

    # Pass through other types (datetime, UUID, Enum, bool, None, etc.)
    return value


# ---------------------------------------------------------------------------
# Result serialization (P1-S3)
# ---------------------------------------------------------------------------


def _orjson_fallback(obj: Any) -> Any:
    """Fallback serializer for types orjson doesn't handle natively.

    Handles:
    - SQLAlchemy Row → dict(row._mapping)
    - Other objects → str(obj)

    Args:
        obj: The object to serialize.

    Returns:
        A JSON-serializable representation.
    """
    # SQLAlchemy Row
    if hasattr(obj, "_mapping"):
        return dict(obj._mapping)

    # Fallback to string representation
    return str(obj)


def serialize_facade_result(result: Any) -> bytes:
    """Serialize a facade method result to JSON bytes.

    Pre-processes the result through _normalize() to mask DB IDs,
    round floats, and convert numpy arrays. Then serializes using
    orjson.dumps() with a fallback for unsupported types.

    Args:
        result: The result from a facade method call.

    Returns:
        JSON bytes (not string). Callers decode as needed.
    """
    normalized = _normalize(result)
    return orjson.dumps(
        normalized,
        default=_orjson_fallback,
        option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
    )


# ---------------------------------------------------------------------------
# Snapshot comparison helpers
# ---------------------------------------------------------------------------


def assert_snapshot_matches(snapshot_name: str, result: Any) -> None:
    """Compare a result against a stored snapshot file.

    If the snapshot doesn't exist, creates it as the baseline.
    If it exists, compares the serialized result against the stored snapshot.

    Args:
        snapshot_name: Name of the snapshot file (without .json extension).
        result: The result to compare.
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOT_DIR / f"{snapshot_name}.json"

    serialized = serialize_facade_result(result)

    if not snapshot_path.exists():
        # First run: create baseline snapshot
        snapshot_path.write_bytes(serialized)
        return

    # Compare against existing snapshot
    expected = snapshot_path.read_bytes()
    assert serialized == expected, (
        f"Snapshot mismatch for {snapshot_name}.\n"
        f"Expected:\n{expected.decode('utf-8')}\n"
        f"Got:\n{serialized.decode('utf-8')}"
    )
