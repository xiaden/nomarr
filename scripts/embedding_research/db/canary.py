"""Post-crash rollback-only verification canary over surviving PK/UNIQUE tables.

DD "Post-crash verification canary": before any ``catalog`` / ``analyze`` /
``report`` read — after a detected post-crash condition, or when ``--verify``
requests it — probe **every** surviving table that carries a ``PRIMARY KEY`` or
``UNIQUE`` constraint by:

1. capturing the exact schema/columns of the table;
2. recording an empty table as ``empty`` (NOT corrupt — CTP-disabled empty tables
   are expected under ``archival_ctp.enabled=false``);
3. for a non-empty table, deterministically selecting the lexicographically
   smallest row under the table's declared key (the first stable ordered row),
4. capturing that sentinel's COMPLETE wide row by explicit column list (all
   columns, including NULLs and every NOT NULL field),
5. beginning a transaction, deleting exactly that sentinel by its key,
6. re-inserting the captured row with the same explicit column list, and
7. rolling back **unconditionally** — probe writes are never committed.

The table inventory is enumerated from DuckDB metadata
(``duckdb_constraints()``) at runtime; it is NOT hardcoded as a permanent list
(the DD explicitly says it does not assume today's inventory is permanent).

Any failure — duplicate-key detection, inability to select/capture/restore the
sentinel, delete-count mismatch, insert/index failure, constraint failure, or any
other probe exception — is a canary failure: it raises
:class:`CanaryCorruptionError`, which blocks the read and instructs the operator
to repair with ``EXPORT DATABASE`` followed by ``IMPORT DATABASE`` into a fresh
DuckDB file. It never continues on a warning and never silently chooses a row.

Timestamps anywhere in the research DB remain integer milliseconds; the canary
itself persists nothing.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "REPAIR_GUIDANCE",
    "CanaryCorruptionError",
    "CanaryProbeReport",
    "detect_post_crash",
    "enumerate_pk_unique_tables",
    "probe_table",
    "run_rollback_canary",
]

#: Exact repair instructions embedded in every canary-failure refusal.
REPAIR_GUIDANCE = (
    "Canary blocked all catalog/analyze/report reads. Repair the DuckDB file with "
    "`EXPORT DATABASE '<dir>'` followed by `IMPORT DATABASE '<dir>'` into a fresh "
    "DuckDB file, then re-run the phase."
)

#: Constraint types the canary probes (a table that declares either carries a
#: reviewed DuckDB ART index whose bookkeeping we exercise).
_KEY_CONSTRAINT_TYPES = ("PRIMARY KEY", "UNIQUE")


class CanaryCorruptionError(RuntimeError):
    """A rollback-only canary probe failed — block reads and demand EXPORT/IMPORT repair."""


@dataclass
class CanaryProbeReport:
    """Per-table canary outcome: mapping of table name to ``'ok'`` or ``'empty'``.

    ``ok`` means the non-empty table survived a delete/re-insert/rollback probe
    byte-identically row-wise; ``empty`` means the table had zero rows (expected,
    e.g. CTP-disabled tables) and required no sentinel.
    """

    tables: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> list[str]:
        return [t for t, s in self.tables.items() if s == "ok"]

    @property
    def empty(self) -> list[str]:
        return [t for t, s in self.tables.items() if s == "empty"]

    @property
    def failed(self) -> bool:
        return False  # a probe failure raises CanaryCorruptionError before a report is returned


def enumerate_pk_unique_tables(con) -> list[tuple[str, tuple[str, ...]]]:
    """Return ``[(table_name, (key_column, ...)), ...]`` for every PK/UNIQUE table.

    Enumerated from DuckDB metadata at runtime (``duckdb_constraints()``), sorted by
    table name for determinism.  A ``PRIMARY KEY`` constraint's implicit ``NOT NULL``
    companion row is filtered out (only ``PRIMARY KEY`` / ``UNIQUE`` are probed).
    """
    rows = con.execute(
        """
        SELECT table_name, constraint_column_names
        FROM duckdb_constraints()
        WHERE constraint_type IN ('PRIMARY KEY', 'UNIQUE')
          AND schema_name = 'main'
        ORDER BY table_name
        """
    ).fetchall()
    # Keep the FIRST declared key set per table (a table declaring both a PRIMARY KEY and
    # a separate UNIQUE keeps its PK as the probe key).  None of the current tables do.
    result: dict[str, tuple[str, ...]] = {}
    for table_name, key_names in rows:
        key_cols = tuple(str(k) for k in key_names)
        if table_name not in result:
            result[table_name] = key_cols
    return [(t, k) for t, k in sorted(result.items())]


def _table_columns(con, table: str) -> tuple[str, ...]:
    return tuple(c[0] for c in con.execute(f"DESCRIBE SELECT * FROM {table}").fetchall())


def _select_sentinel_row(con, table: str, key_cols: tuple[str, ...]):
    """The lexicographically smallest row under the declared key (a stable ordered row)."""
    order = ", ".join(f'"{k}"' for k in key_cols)
    return con.execute(f"SELECT * FROM {table} ORDER BY {order} LIMIT 1").fetchone()


def _delete_sentinel(con, table: str, key_cols: tuple[str, ...], key_vals: list) -> int:
    """Delete exactly the sentinel row by its declared key; return the delete count."""
    where = " AND ".join(f'"{k}" = ?' for k in key_cols)
    res = con.execute(f"DELETE FROM {table} WHERE {where}", list(key_vals))
    row = res.fetchone()
    return int(row[0]) if row is not None else res.rowcount  # type: ignore[union-attr]


def _insert_sentinel(con, table: str, columns: tuple[str, ...], values: list) -> None:
    """Re-insert the captured complete wide row with the same explicit column list."""
    col_csv = ", ".join(f'"{c}"' for c in columns)
    ph = ", ".join("?" for _ in columns)
    con.execute(f"INSERT INTO {table} ({col_csv}) VALUES ({ph})", list(values))


def probe_table(con, table: str, key_cols: tuple[str, ...]) -> str:
    """Probe one PK/UNIQUE table: ``'empty'`` (zero rows) or ``'ok'`` (survived).

    Raises :class:`CanaryCorruptionError` on any failure.  The delete/re-insert
    happens inside a transaction that is rolled back unconditionally — never
    committed.
    """
    count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    if count == 0:
        return "empty"

    columns = _table_columns(con, table)
    try:
        con.execute("BEGIN TRANSACTION")
        sentinel = _select_sentinel_row(con, table, key_cols)
        if sentinel is None:  # row vanished between count and select — treat as corruption
            raise CanaryCorruptionError(
                f"canary could not select a sentinel row for {table}: table changed during probe. {REPAIR_GUIDANCE}"
            )
        key_idx = [columns.index(k) for k in key_cols]
        key_vals = [sentinel[i] for i in key_idx]
        deleted = _delete_sentinel(con, table, key_cols, key_vals)
        if deleted != 1:
            raise CanaryCorruptionError(
                f"canary delete-count mismatch on {table}: deleted {deleted}, expected 1. {REPAIR_GUIDANCE}"
            )
        # Re-insert the captured COMPLETE wide row by explicit column list (all
        # columns incl. NULLs and NOT NULL fields), then roll back unconditionally.
        _insert_sentinel(con, table, columns, list(sentinel))
        con.execute("ROLLBACK")
    except CanaryCorruptionError:
        _safe_rollback(con)
        raise
    except Exception as exc:  # constraint/index/insert failure or any probe exception
        _safe_rollback(con)
        raise CanaryCorruptionError(f"canary probe failed on table {table}: {exc}. {REPAIR_GUIDANCE}") from exc
    return "ok"


def _safe_rollback(con) -> None:
    with suppress(Exception):  # connection already rolled back / closed
        con.execute("ROLLBACK")


def run_rollback_canary(con) -> CanaryProbeReport:
    """Probe every surviving PK/UNIQUE table; return a per-table report.

    Raises :class:`CanaryCorruptionError` on the first failure (before any read may
    proceed).  Empty tables are recorded ``empty`` and never declared corrupt.
    """
    report = CanaryProbeReport()
    for table, key_cols in enumerate_pk_unique_tables(con):
        report.tables[table] = probe_table(con, table, key_cols)
    return report


def detect_post_crash(con, db_path: str | Path | None = None) -> bool:
    """Detect a conservatively-signalled interrupted prior run.

    True when either:

    * a surviving ``<db>.wal`` file exists next to *db_path* (an unclean close may
      have left it behind), or
    * any ``run_provenance`` row has ``status <> 'completed'`` (a started-but-never-
      completed / failed prior phase run).

    This is a thin detection gate only; it performs no probes itself.  A clean run
    (no ``.wal``, no non-complete provenance row) returns False so normal runs pay no
    canary probe cost.  Detection signals are documented exactly (see annotation).
    """
    if db_path is not None:
        wal = Path(str(db_path) + ".wal")
        if wal.exists():
            return True
    try:
        n = con.execute("SELECT count(*) FROM run_provenance WHERE status <> 'completed'").fetchone()[0]
        return int(n) > 0
    except Exception:  # pragma: no cover - run_provenance absent / unreadable
        return False
