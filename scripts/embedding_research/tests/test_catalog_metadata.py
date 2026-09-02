"""Plan C Phase 4 — catalog_metadata singleton helpers.

Covers ``scripts.embedding_research/db/catalog_metadata.py``: the singleton
update-or-insert write path (``update_catalog_metadata``), the ``>1``-row corruption
guard shared by ``read_catalog_metadata`` and the write path, and the populated-row read
branch.  Uses a real in-memory DuckDB connection (the ``con`` fixture in conftest has the
full schema applied).  Mirrors the conventions in ``tests/test_segmentation.py`` and
``tests/test_provenance.py``.
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.db.catalog_metadata import (
    CATALOG_METADATA_TABLE,
    CatalogMetadataCorruptionError,
    catalog_metadata_columns,
    read_catalog_metadata,
    update_catalog_metadata,
)

EXPECTED_COLUMNS = {
    "catalog_semantics_version": "INTEGER",
    "serialization_version": "INTEGER",
    "manifest_version": "INTEGER",
    "backbone_set": "VARCHAR",
    "latest_catalog_run_id": "VARCHAR",
    "latest_config_ids": "VARCHAR",
    "reconciled_at": "BIGINT",
}


def _columns(con, table: str) -> dict[str, str]:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = 'main' ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return dict(rows)


def _constraint_kinds(con, table: str) -> list[str]:
    rows = con.execute("SELECT constraint_type FROM duckdb_constraints() WHERE table_name = ?", [table]).fetchall()
    return [r[0] for r in rows]


def _row_count(con) -> int:
    return int(con.execute(f"SELECT count(*) FROM {CATALOG_METADATA_TABLE}").fetchone()[0])


def _meta_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "catalog_semantics_version": 1,
        "serialization_version": 1,
        "manifest_version": 1,
        "backbone_set": "effnet,musicnn",
        "latest_catalog_run_id": "run-cat-1",
        "latest_config_ids": "1,2",
        "reconciled_at": 1_700_000_000_000,
    }
    values.update(overrides)
    return values


def test_catalog_metadata_table_schema(con):
    """Scalar-only singleton; no PK/UNIQUE constraint (DuckDB ART/WAL policy)."""
    assert _columns(con, CATALOG_METADATA_TABLE) == EXPECTED_COLUMNS
    kinds = _constraint_kinds(con, CATALOG_METADATA_TABLE)
    assert "PRIMARY KEY" not in kinds
    assert "UNIQUE" not in kinds
    assert set(kinds) <= {"NOT NULL"}


def test_update_inserts_singleton_when_empty(con):
    update_catalog_metadata(con, **_meta_values())
    assert _row_count(con) == 1
    state = read_catalog_metadata(con)
    assert state is not None
    for key in catalog_metadata_columns:
        assert state[key] == _meta_values()[key]


def test_update_reuses_singleton_row_on_rerun(con):
    """A second update must UPDATE the existing row, never create a duplicate."""
    update_catalog_metadata(con, **_meta_values())
    update_catalog_metadata(
        con,
        **_meta_values(
            latest_catalog_run_id="run-cat-2",
            latest_config_ids="3",
            reconciled_at=1_700_000_100_000,
        ),
    )
    assert _row_count(con) == 1
    state = read_catalog_metadata(con)
    assert state is not None
    assert state["latest_catalog_run_id"] == "run-cat-2"
    assert state["latest_config_ids"] == "3"
    assert state["reconciled_at"] == 1_700_000_100_000


def test_read_empty_returns_none(con):
    assert read_catalog_metadata(con) is None


def test_multi_row_corruption_raises_on_write_and_read(con):
    """More than one row is corruption; neither the write nor the read may proceed silently."""
    con.execute(
        f"INSERT INTO {CATALOG_METADATA_TABLE} ({', '.join(catalog_metadata_columns)}) "
        "VALUES (1, 1, 1, 'effnet', 'r1', '1', 1000)"
    )
    con.execute(
        f"INSERT INTO {CATALOG_METADATA_TABLE} ({', '.join(catalog_metadata_columns)}) "
        "VALUES (1, 1, 1, 'effnet', 'r2', '2', 2000)"
    )
    with pytest.raises(CatalogMetadataCorruptionError):
        update_catalog_metadata(con, **{k: _meta_values()[k] for k in catalog_metadata_columns})
    with pytest.raises(CatalogMetadataCorruptionError):
        read_catalog_metadata(con)
    # A corrupt state is never silently overwritten: still two rows after the failed write.
    assert _row_count(con) == 2


def test_catalog_metadata_corruption_error_is_runtime_error():
    assert issubclass(CatalogMetadataCorruptionError, RuntimeError)
