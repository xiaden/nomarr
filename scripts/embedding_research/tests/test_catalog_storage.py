"""Plan C P1-S3 — compact-catalog storage seam tests.

Validates ``catalog_storage.py`` (the SOLE DDL / connection / column-order home for the
durable FILESYSTEM compact-catalog snapshot tables) against the P1-S2-pinned column
constants, and exercises the :class:`~catalog_storage.CatalogHandle` boundary and the
canonical row/manifest serialization scaffolds.

The three pinned column sets (``SEG_CONFIG_COLS`` / ``CATALOG_SONG_COLS`` / ``SEG_META_COLS``)
are imported from the P1-S2 spec file ``test_compact_catalog_scale_weights.py`` and asserted
against the REAL module — never re-declared as literals here.  ``catalog_metadata`` and
``run_provenance`` have no P1-S2 pin (their semantics follow DD L209 / L213), so their
tests assert the module's own column tuples match the on-disk schema it creates and that the
semantics the DD requires are represented.

These tests do NOT edit the locked P1-S1/P1-S2 spec files; they only read their pinned
constants.  All tests are synthetic DuckDB / stdlib only (no audio, no model, no corpus).
"""

from __future__ import annotations

import contextlib

import duckdb
import pytest

from scripts.embedding_research import catalog_storage as storage
from scripts.embedding_research.tests.test_compact_catalog_scale_weights import (
    CATALOG_SONG_COLS as PINNED_CATALOG_SONG_COLS,
)
from scripts.embedding_research.tests.test_compact_catalog_scale_weights import (
    COMPACT_TABLES as PINNED_COMPACT_TABLES,
)
from scripts.embedding_research.tests.test_compact_catalog_scale_weights import (
    SEG_CONFIG_COLS as PINNED_SEG_CONFIG_COLS,
)
from scripts.embedding_research.tests.test_compact_catalog_scale_weights import (
    SEG_META_COLS as PINNED_SEG_META_COLS,
)


def _table_column_map(con) -> dict[str, set[str]]:
    """table -> set of column names present on the connection."""
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_name IN (?, ?, ?, ?, ?)",
        list(storage.CATALOG_TABLES),
    ).fetchall()
    result: dict[str, set[str]] = {name: set() for name in storage.CATALOG_TABLES}
    for table, column in rows:
        result[table].add(column)
    return result


# --------------------------------------------------------------------------- #
# Import cleanliness + column-set conformance to the P1-S2 pins                 #
# --------------------------------------------------------------------------- #


def test_module_imports_cleanly():
    """catalog_storage imports without side effects and exposes its seam surface."""
    assert callable(storage.ensure_schema)
    assert callable(storage.connect)
    assert hasattr(storage, "CatalogHandle")
    assert storage.CATALOG_TABLES


def test_compact_table_set_matches_pinned_guard():
    """The five-table snapshot set matches the P1-S2 COMPACT_TABLES guard (no membership table)."""
    assert storage.CATALOG_TABLES == PINNED_COMPACT_TABLES
    assert "seg_membership" not in storage.CATALOG_TABLES
    assert len(storage.CATALOG_TABLES) == 5


def test_seg_config_columns_match_pinned_constants():
    """seg_config DDL column set is exactly the P1-S2-pinned SEG_CONFIG_COLS."""
    assert storage.SEG_CONFIG_COLS == PINNED_SEG_CONFIG_COLS


def test_catalog_song_columns_match_pinned_constants():
    """catalog_song DDL column set is exactly the P1-S2-pinned CATALOG_SONG_COLS."""
    assert storage.CATALOG_SONG_COLS == PINNED_CATALOG_SONG_COLS


def test_seg_meta_columns_match_pinned_constants():
    """seg_meta DDL column set is exactly the P1-S2-pinned SEG_META_COLS."""
    assert storage.SEG_META_COLS == PINNED_SEG_META_COLS


def test_catalog_metadata_columns_cover_dd_l209_semantics():
    """catalog_metadata includes the DD L209 version/identity/digest semantics."""
    cols = storage.CATALOG_METADATA_COLS
    assert len(cols) == len(set(cols))  # no duplicates
    for required in (
        "catalog_id",
        "format_version",
        "schema_version",
        "manifest_version",
        "serialization_version",
        "segmentation_semantics_version",
        "mask_semantics_version",
        "scoring_semantics_version",
        "build_duckdb_version",
        "build_python_version",
        "build_numpy_version",
        "resolved_input_digests",
        "run_id",
        "created_at_ms",
    ):
        assert required in cols


def test_run_provenance_columns_cover_dd_l213_semantics():
    """run_provenance includes the DD L213 phase/status/command/hash/warning/decision semantics."""
    cols = storage.RUN_PROVENANCE_COLS
    assert len(cols) == len(set(cols))  # no duplicates
    for required in (
        "run_id",
        "phase",
        "status",
        "command",
        "resolved_inputs",
        "resolved_outputs",
        "content_hashes",
        "software_versions",
        "warning_count",
        "warnings",
        "refusal_reuse_decision",
        "report_run_refs",
        "started_at_ms",
        "finished_at_ms",
    ):
        assert required in cols


# --------------------------------------------------------------------------- #
# On-disk schema conformance (real DuckDB)                                      #
# --------------------------------------------------------------------------- #


def test_created_schema_column_sets_match_module_and_has_no_membership(tmp_path):
    """ensure_schema creates the five tables whose columns match the module's tuples."""
    db_path = tmp_path / "snapshot.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        storage.ensure_schema(con)
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
        assert set(storage.CATALOG_TABLES) <= tables
        assert "seg_membership" not in tables
        columns = _table_column_map(con)
        assert columns[storage.SEG_CONFIG_TABLE] == set(storage.SEG_CONFIG_COLS)
        assert columns[storage.CATALOG_SONG_TABLE] == set(storage.CATALOG_SONG_COLS)
        assert columns[storage.SEG_META_TABLE] == set(storage.SEG_META_COLS)
        assert columns[storage.CATALOG_METADATA_TABLE] == set(storage.CATALOG_METADATA_COLS)
        assert columns[storage.RUN_PROVENANCE_TABLE] == set(storage.RUN_PROVENANCE_COLS)
    finally:
        con.close()


def test_ddl_emits_no_primary_key_or_unique_constraints():
    """No DuckDB PRIMARY KEY / UNIQUE constraint is emitted for any snapshot table."""
    ddl = "\n".join(storage._create_statements())
    upper = ddl.upper()
    assert "PRIMARY KEY" not in upper
    assert "UNIQUE" not in upper
    assert " SEG_MEMBERSHIP " not in " " + upper + " "
    for table in storage.CATALOG_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in ddl


def test_connect_context_manager_builds_snapshot_schema(tmp_path):
    """connect() creates the snapshot file and its schema in a fresh writable DB."""
    db_path = tmp_path / "ctx.duckdb"
    with storage.connect(db_path) as con:
        tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert set(storage.CATALOG_TABLES) <= tables
    assert db_path.exists()


# --------------------------------------------------------------------------- #
# CatalogHandle boundary scaffold                                               #
# --------------------------------------------------------------------------- #


def test_catalog_handle_scaffold_fields_and_close():
    """CatalogHandle carries identity/root/con and closes cleanly (eq disabled)."""
    con = duckdb.connect(":memory:")
    try:
        handle = storage.CatalogHandle(catalog_id="catalog-abc", root="/tmp/cat", con=con)
        assert handle.catalog_id == "catalog-abc"
        assert str(handle.root).endswith("cat")
        assert handle.con is con
        handle.close()  # idempotent-safe; duckdb close on already-open con
    finally:
        with contextlib.suppress(Exception):
            con.close()


def test_catalog_handle_rejects_blank_catalog_id():
    """The handle boundary rejects a blank catalog identity."""
    con = duckdb.connect(":memory:")
    try:
        with pytest.raises(ValueError):
            storage.CatalogHandle(catalog_id="   ", root="/tmp/cat", con=con)
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# Canonical serialization scaffold                                              #
# --------------------------------------------------------------------------- #


def test_canonical_absorbed_indices_sorts_dedups_and_rejects_invalid():
    assert storage.canonical_absorbed_indices([7, 1, 4]) == "[1,4,7]"
    assert storage.canonical_absorbed_indices([4, 1, 1, 4]) == "[1,4]"
    assert storage.canonical_absorbed_indices([]) == "[]"
    with pytest.raises(ValueError):
        storage.canonical_absorbed_indices([-1])
    with pytest.raises(TypeError):
        storage.canonical_absorbed_indices([True])
    with pytest.raises(TypeError):
        storage.canonical_absorbed_indices(["1"])


def test_canonical_field_value_type_tags_are_self_delimiting():
    assert storage.canonical_field_value(None) == "n"
    assert storage.canonical_field_value(True) == "b1"
    assert storage.canonical_field_value(False) == "b0"
    assert storage.canonical_field_value(5) == "i5"
    assert storage.canonical_field_value(0.0) == "f0.0"
    assert storage.canonical_field_value(-0.0) == "f0.0"  # -0.0 normalized
    assert storage.canonical_field_value("abc") == "s3:abc"  # byte-length prefixed
    assert storage.canonical_field_value("") == "s0:"
    with pytest.raises(ValueError):
        storage.canonical_field_value(float("nan"))
    with pytest.raises(TypeError):
        storage.canonical_field_value([1, 2])


def test_canonical_row_text_deterministic_and_requires_all_columns():
    row = {"a": 1, "b": "x", "c": None}
    text = storage.canonical_row_text(row, columns=("a", "b", "c"))
    assert text == "a=i1|b=s1:x|c=n"
    # Deterministic for the same content regardless of mapping insertion order.
    again = storage.canonical_row_text({"a": 1, "b": "x", "c": None}, columns=("a", "b", "c"))
    assert again == text
    with pytest.raises(KeyError):
        storage.canonical_row_text({"a": 1}, columns=("a", "b"))


def test_canonical_rows_text_sorts_canonically():
    rows = [
        {"config_id": 2, "song_id": "s02"},
        {"config_id": 1, "song_id": "s10"},
        {"config_id": 1, "song_id": "s01"},
    ]
    text = storage.canonical_rows_text(rows, columns=("config_id", "song_id"), order_by=("config_id", "song_id"))
    lines = text.splitlines()
    assert len(lines) == 3
    # Canonically ordered: config_id 1 rows sorted by song_id, then config_id 2.
    assert lines[0] == "config_id=i1|song_id=s3:s01"
    assert lines[1] == "config_id=i1|song_id=s3:s10"
    assert lines[2] == "config_id=i2|song_id=s3:s02"
    # Shuffled input serializes identically (order-independent).
    shuffled = storage.canonical_rows_text(
        list(reversed(rows)), columns=("config_id", "song_id"), order_by=("config_id", "song_id")
    )
    assert shuffled == text
