"""Post-run provenance and singleton corpus-state helpers (Plan B Phase 2).

Two Plan-B base surfaces (Plan C extends usage on these SAME tables — it never
recreates them):

* ``run_provenance`` — one row per completed phase run (``run_id`` is an application
  string; NO ``PRIMARY KEY``/``UNIQUE``, matching DuckDB ART/WAL policy).  ``retained``
  protects a row from manifest/view GC; ``view_refs`` is a root-relative view-ref
  column holding disposable search-view references (``keyset_hash|content_hash|view_ref`` lines)
  written by the Plan D analyze path.
* ``corpus_state`` — a strict SINGLETON: every write verifies zero-or-one rows first and
  raises when more than one exists (that is corruption).  Fields Plan C owns later
  (``latest_catalog_run_id``) are written empty/NULL here.

Timestamps are INTEGER milliseconds (the project wall-clock convention).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "corpus_state_columns",
    "read_corpus_state",
    "read_run_provenance",
    "run_provenance_columns",
    "update_corpus_state",
    "write_run_provenance",
]

RUN_PROVENANCE_TABLE = "run_provenance"
CORPUS_STATE_TABLE = "corpus_state"

#: Exact ``run_provenance`` column order (DDL / ledger RunProvenanceRecord field order).
run_provenance_columns: tuple[str, ...] = (
    "run_id",
    "phase",
    "status",
    "started_at",
    "finished_at",
    "input_artifact_hashes",
    "output_artifact_hashes",
    "config_hash",
    "song_count",
    "warning_count",
    "software_versions",
    "command_line",
    "structural_change_summary",
    "retained",
    "view_refs",
)

#: Exact ``corpus_state`` column order (DDL / ledger CatalogState field order).
corpus_state_columns: tuple[str, ...] = (
    "state_version",
    "registered_song_count",
    "eligible_song_count",
    "complete_flag",
    "latest_catalog_run_id",
    "reconciled_at",
    "reconciliation_status",
)


class CorpusStateCorruptionError(RuntimeError):
    """``corpus_state`` holds more than one row — the singleton invariant is broken."""


def _insert_row(con, table: str, columns: tuple[str, ...], values: Mapping[str, object]) -> None:
    col_csv = ", ".join(columns)
    placeholders = ", ".join(f"${col}" for col in columns)
    con.execute(
        f"INSERT INTO {table} ({col_csv}) VALUES ({placeholders})",
        {col: values.get(col) for col in columns},
    )


def write_run_provenance(
    con,
    *,
    run_id: str,
    phase: str,
    status: str,
    started_at: int,
    finished_at: int | None = None,
    input_artifact_hashes: str = "",
    output_artifact_hashes: str = "",
    config_hash: str = "",
    song_count: int = 0,
    warning_count: int = 0,
    software_versions: str = "",
    command_line: str = "",
    structural_change_summary: str = "",
    retained: bool = False,
    view_refs: str = "",
) -> None:
    """Append one ``run_provenance`` row for a completed phase run.

    Scalar columns only, no PK/UNIQUE (``run_id`` is an application string).  ``retained``
    must be explicit: a run row is only protected from manifest/view GC when the caller
    opts in.  Timestamps are integer milliseconds.
    """
    _insert_row(
        con,
        RUN_PROVENANCE_TABLE,
        run_provenance_columns,
        {
            "run_id": run_id,
            "phase": phase,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "input_artifact_hashes": input_artifact_hashes,
            "output_artifact_hashes": output_artifact_hashes,
            "config_hash": config_hash,
            "song_count": song_count,
            "warning_count": warning_count,
            "software_versions": software_versions,
            "command_line": command_line,
            "structural_change_summary": structural_change_summary,
            "retained": retained,
            "view_refs": view_refs,
        },
    )


def read_run_provenance(con, *, run_id: str | None = None) -> list[dict]:
    """Return ``run_provenance`` rows as dicts (all rows, or filtered by ``run_id``)."""
    col_csv = ", ".join(run_provenance_columns)
    if run_id is not None:
        sql = f"SELECT {col_csv} FROM {RUN_PROVENANCE_TABLE} WHERE run_id = $run_id"
        rows = con.execute(sql, {"run_id": run_id}).fetchall()
    else:
        sql = f"SELECT {col_csv} FROM {RUN_PROVENANCE_TABLE}"
        rows = con.execute(sql).fetchall()
    return [dict(zip(run_provenance_columns, row, strict=True)) for row in rows]


def _count_rows(con, table: str) -> int:
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def read_corpus_state(con) -> dict | None:
    """Return the single ``corpus_state`` row as a dict, or None when empty.

    Raises :class:`CorpusStateCorruptionError` if the singleton invariant is broken
    (more than one row present).
    """
    count = _count_rows(con, CORPUS_STATE_TABLE)
    if count > 1:
        raise CorpusStateCorruptionError(f"corpus_state singleton corrupted: {count} rows present (expected 0 or 1)")
    col_csv = ", ".join(corpus_state_columns)
    row = con.execute(f"SELECT {col_csv} FROM {CORPUS_STATE_TABLE} LIMIT 1").fetchone()
    if row is None:
        return None
    return dict(zip(corpus_state_columns, row, strict=True))


def update_corpus_state(
    con,
    *,
    state_version: int = 1,
    registered_song_count: int = 0,
    eligible_song_count: int = 0,
    complete_flag: bool = False,
    latest_catalog_run_id: str = "",
    reconciled_at: int,
    reconciliation_status: str = "",
) -> None:
    """Update-or-insert the singleton ``corpus_state`` row inside ONE transaction.

    First verifies the zero-or-one-row invariant and raises
    :class:`CorpusStateCorruptionError` when more than one row exists (corruption), so a
    corrupt state can never be silently overwritten.  Fields Plan C owns later are written
    empty/NULL now.  ``reconciled_at`` is an integer-millisecond timestamp.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        count = _count_rows(con, CORPUS_STATE_TABLE)
        if count > 1:
            raise CorpusStateCorruptionError(
                f"corpus_state singleton corrupted: {count} rows present (expected 0 or 1)"
            )
        values = {
            "state_version": state_version,
            "registered_song_count": registered_song_count,
            "eligible_song_count": eligible_song_count,
            "complete_flag": complete_flag,
            "latest_catalog_run_id": latest_catalog_run_id,
            "reconciled_at": reconciled_at,
            "reconciliation_status": reconciliation_status,
        }
        if count == 0:
            _insert_row(con, CORPUS_STATE_TABLE, corpus_state_columns, values)
        else:
            sets = ", ".join(f"{col} = ${col}" for col in corpus_state_columns)
            con.execute(f"UPDATE {CORPUS_STATE_TABLE} SET {sets}", values)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
