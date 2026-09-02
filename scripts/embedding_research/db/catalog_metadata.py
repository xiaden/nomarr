"""Catalog-level metadata singleton helpers (Plan C, Phase 4).

``catalog_metadata`` is a small metadata-only SINGLETON (zero-or-one row, exactly like
``corpus_state``; more than one row is corruption) carrying the identity-relevant
versions and latest identifiers the DD's catalog-metadata block and the shared ledger
require:

``catalog_metadata(catalog_semantics_version, serialization_version, manifest_version,
                   backbone_set, latest_catalog_run_id, latest_config_ids, reconciled_at)``

* ``catalog_semantics_version`` — the catalog semantics / segmentation-semantics contract
  version that (when it changes) invalidates ``search_view_hash``.
* ``serialization_version`` — the canonical serialization ordering/encoding contract
  version (changing it changes every identity hash — the "ordering-contract change" axis).
* ``manifest_version`` — the manifest format version that feeds identity hashes.
* ``backbone_set`` — the sorted, comma-joined canonical backbone text in the catalog.
* ``latest_catalog_run_id`` / ``latest_config_ids`` — the most recent catalog run and the
  config ids it produced (latest run/config identifiers).

Scalar columns only, NO ``PRIMARY KEY``/``UNIQUE`` (DuckDB ART/WAL policy).  This table
NEVER stores ``catalog_fingerprint`` — that value is manifest-only and non-self-referential
(the DD's ``corpus_state`` deliberately has no ``catalog_fingerprint`` column either).

Every write mirrors ``provenance.update_corpus_state``: it first verifies the zero-or-one
row invariant and raises :class:`CatalogMetadataCorruptionError` when more than one row
exists, then ``UPDATE``s the existing row or inserts the sole row inside one transaction.
Timestamps are INTEGER milliseconds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CATALOG_METADATA_TABLE",
    "CatalogMetadataCorruptionError",
    "catalog_metadata_columns",
    "read_catalog_metadata",
    "update_catalog_metadata",
]

CATALOG_METADATA_TABLE = "catalog_metadata"

#: Exact ``catalog_metadata`` column order (DDL / ledger field order).
catalog_metadata_columns: tuple[str, ...] = (
    "catalog_semantics_version",
    "serialization_version",
    "manifest_version",
    "backbone_set",
    "latest_catalog_run_id",
    "latest_config_ids",
    "reconciled_at",
)


class CatalogMetadataCorruptionError(RuntimeError):
    """``catalog_metadata`` holds more than one row — the singleton invariant is broken."""


def _count_rows(con, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _insert_row(con, table: str, columns: tuple[str, ...], values: Mapping[str, object]) -> None:
    col_csv = ", ".join(columns)
    placeholders = ", ".join(f"${col}" for col in columns)
    con.execute(
        f"INSERT INTO {table} ({col_csv}) VALUES ({placeholders})",
        {col: values.get(col) for col in columns},
    )


def read_catalog_metadata(con) -> dict | None:
    """Return the single ``catalog_metadata`` row as a dict, or None when empty.

    Raises :class:`CatalogMetadataCorruptionError` if the singleton invariant is broken
    (more than one row present).
    """
    count = _count_rows(con, CATALOG_METADATA_TABLE)
    if count > 1:
        raise CatalogMetadataCorruptionError(
            f"catalog_metadata singleton corrupted: {count} rows present (expected 0 or 1)"
        )
    col_csv = ", ".join(catalog_metadata_columns)
    row = con.execute(f"SELECT {col_csv} FROM {CATALOG_METADATA_TABLE} LIMIT 1").fetchone()
    if row is None:
        return None
    return dict(zip(catalog_metadata_columns, row, strict=True))


def update_catalog_metadata(
    con,
    *,
    catalog_semantics_version: int,
    serialization_version: int,
    manifest_version: int,
    backbone_set: str = "",
    latest_catalog_run_id: str = "",
    latest_config_ids: str = "",
    reconciled_at: int,
) -> None:
    """Update-or-insert the singleton ``catalog_metadata`` row inside ONE transaction.

    First verifies the zero-or-one-row invariant and raises
    :class:`CatalogMetadataCorruptionError` when more than one row exists (corruption), so
    a corrupt state can never be silently overwritten.  ``reconciled_at`` is an
    integer-millisecond timestamp.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        count = _count_rows(con, CATALOG_METADATA_TABLE)
        if count > 1:
            raise CatalogMetadataCorruptionError(
                f"catalog_metadata singleton corrupted: {count} rows present (expected 0 or 1)"
            )
        values = {
            "catalog_semantics_version": catalog_semantics_version,
            "serialization_version": serialization_version,
            "manifest_version": manifest_version,
            "backbone_set": backbone_set,
            "latest_catalog_run_id": latest_catalog_run_id,
            "latest_config_ids": latest_config_ids,
            "reconciled_at": reconciled_at,
        }
        if count == 0:
            _insert_row(con, CATALOG_METADATA_TABLE, catalog_metadata_columns, values)
        else:
            sets = ", ".join(f"{col} = ${col}" for col in catalog_metadata_columns)
            con.execute(f"UPDATE {CATALOG_METADATA_TABLE} SET {sets}", values)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
