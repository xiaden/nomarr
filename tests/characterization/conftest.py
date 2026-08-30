"""Shared fixtures and helpers for characterization tests.

Provides:
- Session-scoped PostgreSQL container via testcontainers
- Alembic migration runner against the test database
- Database instance with seed data factory
- Result normalizer and serializer for snapshot comparisons
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson
import pytest
from alembic.config import Config as AlembicConfig
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from nomarr.helpers.dataclasses.library_dataclass import Library
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
def test_db_url(postgres_container) -> str:
    """Build the SQLAlchemy URL for the test database.

    Uses psycopg2 (sync driver) for Alembic migrations and Database facade.
    """
    pg = postgres_container
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


# ---------------------------------------------------------------------------
# Function-scoped fixtures: seed data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_data(db):
    """Insert seed data into the test database using the sealed domain facade.

    Phase 6 (song-tag correction): seed creation now goes through the domain
    contracts — ``create_library(Library)``, ``add_song_to_library(Library, …)``,
    ``ensure_tag(TagRef)``, ``replace_song_tags(SongIdentity, …)`` and
    ``start_scan(Library, …)``. Storage ids are never passed to callers; song
    ids are returned so tests can resolve them through the identity bridge.

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
        "tags": [],
        "scans": [],
    }

    # Create 2 libraries (domain values)
    lib1 = db.library.create_library(Library(name="TestLib1", root_path="/tmp/test1"))
    lib2 = db.library.create_library(Library(name="TestLib2", root_path="/tmp/test2"))
    created["libraries"] = [lib1, lib2]

    # Create 3 songs (2 in lib1, 1 in lib2); returns storage song ids.
    now_ms_val = now_ms()
    song1_id = db.library.add_song_to_library(
        lib1,
        {
            "path": "/tmp/test1/song1.flac",
            "normalized_path": "/tmp/test1/song1.flac",
            "file_size": 1024000,
            "modified_time": now_ms_val.value,
            "duration_seconds": 180.5,
            "needs_tagging": 0,
            "is_valid": 1,
            "tagged": 0,
        },
    )
    song2_id = db.library.add_song_to_library(
        lib1,
        {
            "path": "/tmp/test1/song2.mp3",
            "normalized_path": "/tmp/test1/song2.mp3",
            "file_size": 512000,
            "modified_time": now_ms_val.value,
            "duration_seconds": 240.0,
            "needs_tagging": 1,
            "is_valid": 1,
            "tagged": 0,
        },
    )
    song3_id = db.library.add_song_to_library(
        lib2,
        {
            "path": "/tmp/test2/song3.flac",
            "normalized_path": "/tmp/test2/song3.flac",
            "file_size": 2048000,
            "modified_time": now_ms_val.value,
            "duration_seconds": 300.0,
            "needs_tagging": 0,
            "is_valid": 1,
            "tagged": 1,
        },
    )
    created["songs"] = [song1_id, song2_id, song3_id]

    # Create 5 tags via the domain identity (never a storage id).
    tag1 = db.library.ensure_tag(TagRef(name="nom:mood-strict", value="happy", namespace="nom"))
    tag2 = db.library.ensure_tag(TagRef(name="nom:mood-strict", value="sad", namespace="nom"))
    tag3 = db.library.ensure_tag(TagRef(name="nom:genre", value="rock", namespace="nom"))
    tag4 = db.library.ensure_tag(TagRef(name="nom:genre", value="jazz", namespace="nom"))
    tag5 = db.library.ensure_tag(TagRef(name="nom:tempo", value="fast", namespace="nom"))
    created["tags"] = [tag1, tag2, tag3, tag4, tag5]

    # Assign tags to songs via the natural identity + domain assignments.
    song1 = db.library.resolve_song_identity(song1_id)
    song2 = db.library.resolve_song_identity(song2_id)
    assert song1 is not None and song2 is not None
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


def _normalize(value: Any) -> Any:
    """Normalize a value for snapshot comparison.

    Applies the following transformations recursively:
    - DB IDs (integers > 1000) → "<DB_ID>"
    - Floats → rounded to 6 decimal places
    - numpy ndarray → .tolist()
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

    # DB ID masking: integers > 1000 are likely database IDs
    if isinstance(value, int) and not isinstance(value, bool) and value > 1000:
        return "<DB_ID>"

    # Float rounding: 6 decimal places
    if isinstance(value, float):
        return round(value, 6)

    # Recursive normalization for containers
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize(item) for item in value)

    # Pass through other types (datetime, UUID, Enum, str, bool, None, etc.)
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
