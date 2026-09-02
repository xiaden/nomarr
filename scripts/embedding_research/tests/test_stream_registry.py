"""DuckDB registry DDL + application-level duplicate guard tests (Plan B Phase 1, P1-S4).

Proves the two new tables exist with EXACTLY the DD column set and data types, that
neither carries a ``PRIMARY KEY``/``UNIQUE`` constraint, that DuckDB itself tolerates a
duplicate logical identity (so uniqueness is purely application-level), and that the
public app-level guards (re-exported through ``db``) reject a second row without
replacement.
"""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.db import (
    raise_if_head_duplicate,
    raise_if_stream_duplicate,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.streams.records import DuplicateStreamError

#: Expected stream_registry columns -> DuckDB reportable data type.
STREAM_EXPECTED = {
    "song_id": "VARCHAR",
    "backbone": "VARCHAR",
    "artifact_ref": "VARCHAR",
    "patch_count": "INTEGER",
    "dim": "INTEGER",
    "dtype": "VARCHAR",
    "format_version": "VARCHAR",
    "fingerprint_sha256": "VARCHAR",
    "preprocess_fn": "VARCHAR",
    "preprocess_version": "VARCHAR",
    "backbone_model_hash": "VARCHAR",
    "audio_params": "VARCHAR",
    "embed_semantics_version": "INTEGER",
    "provenance_source": "VARCHAR",
    "provenance_assumption": "VARCHAR",
    "status": "VARCHAR",
    "run_id": "VARCHAR",
    "created_at": "BIGINT",
    "updated_at": "BIGINT",
}

HEAD_EXPECTED = {
    "song_id": "VARCHAR",
    "backbone": "VARCHAR",
    "artifact_ref": "VARCHAR",
    "patch_count": "INTEGER",
    "head_ids": "VARCHAR",
    "dim_by_head": "VARCHAR",
    "format_version": "VARCHAR",
    "fingerprint_sha256": "VARCHAR",
    "preprocess_fn": "VARCHAR",
    "preprocess_version": "VARCHAR",
    "backbone_model_hash": "VARCHAR",
    "alignment_version": "VARCHAR",
    "status": "VARCHAR",
    "run_id": "VARCHAR",
    "created_at": "BIGINT",
    "updated_at": "BIGINT",
}


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _columns(con, table: str) -> dict[str, str]:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return dict(rows)


def _constraint_types(con, table: str) -> list[str]:
    rows = con.execute("SELECT constraint_type FROM duckdb_constraints() WHERE table_name = ?", [table]).fetchall()
    return [r[0] for r in rows]


def test_stream_registry_ddl_columns_and_types(con):
    assert _columns(con, "stream_registry") == STREAM_EXPECTED


def test_head_stream_registry_ddl_columns_and_types(con):
    assert _columns(con, "head_stream_registry") == HEAD_EXPECTED


@pytest.mark.parametrize("table", ["stream_registry", "head_stream_registry"])
def test_no_primary_key_or_unique_constraint(con, table):
    types = _constraint_types(con, table)
    assert "PRIMARY KEY" not in types
    assert "UNIQUE" not in types
    # No UNIQUE-index-backed constraint either.
    assert not con.execute("SELECT 1 FROM duckdb_indexes() WHERE table_name = ? AND is_unique", [table]).fetchall()


def test_duckdb_permits_duplicate_identity_without_db_constraint(con):
    """Raw SQL can insert a duplicate (song_id, backbone): uniqueness is app-level only."""
    columns = "song_id, backbone, artifact_ref, patch_count, dim, dtype, format_version, fingerprint_sha256, embed_semantics_version, provenance_source, status, run_id, created_at, updated_at"
    values = (
        "'s1', 'effnet', 'patches/a.npy', 3, 4, 'float32', '1', "
        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 1, 'embed', 'ready', 'r1', 1, 1"
    )
    for _ in range(2):
        con.execute(f"INSERT INTO stream_registry ({columns}) VALUES ({values})")
    count = con.execute("SELECT count(*) FROM stream_registry WHERE song_id = 's1' AND backbone = 'effnet'").fetchone()[
        0
    ]
    assert count == 2


def test_app_guard_rejects_duplicate_stream(con):
    raise_if_stream_duplicate(con, "s1", "effnet")  # first is free
    insert = "INSERT INTO stream_registry (song_id, backbone, artifact_ref, patch_count, dim, dtype, format_version, fingerprint_sha256, embed_semantics_version, provenance_source, status, run_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    con.execute(
        insert,
        ["s1", "effnet", "patches/a.npy", 3, 4, "float32", "1", "a" * 64, 1, "embed", "ready", "r1", 1, 1],
    )
    with pytest.raises(DuplicateStreamError):
        raise_if_stream_duplicate(con, "s1", "effnet")


def test_app_guard_rejects_duplicate_head(con):
    raise_if_head_duplicate(con, "s1", "effnet")
    insert = (
        "INSERT INTO head_stream_registry (song_id, backbone, artifact_ref, patch_count, head_ids, "
        "dim_by_head, format_version, fingerprint_sha256, alignment_version, status, run_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    con.execute(
        insert,
        ["s1", "effnet", "heads/a.npz", 3, "timbre", "timbre=2", "1", "a" * 64, "v1", "ready", "r1", 1, 1],
    )
    with pytest.raises(DuplicateStreamError):
        raise_if_head_duplicate(con, "s1", "effnet")
