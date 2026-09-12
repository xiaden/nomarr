"""Geometry-era run provenance and corpus-state helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

RUN_PROVENANCE_TABLE = "run_provenance"
CORPUS_STATE_TABLE = "corpus_state"
run_provenance_columns = (
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
)
corpus_state_columns = (
    "state_version",
    "registered_song_count",
    "eligible_song_count",
    "complete_flag",
    "reconciled_at",
    "reconciliation_status",
)


class CorpusStateCorruptionError(RuntimeError):
    pass


def _insert_row(con, table: str, columns: tuple[str, ...], values: Mapping[str, object]) -> None:
    cols = ", ".join(columns)
    con.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({', '.join(f'${c}' for c in columns)})",
        {c: values.get(c) for c in columns},
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
) -> None:
    """Persist one phase-run provenance row with its exact input/output hashes."""
    _insert_row(con, RUN_PROVENANCE_TABLE, run_provenance_columns, locals())


def read_run_provenance(con, *, run_id: str | None = None) -> list[dict]:
    """Read retained run provenance, optionally restricted to one run identifier."""
    cols = ", ".join(run_provenance_columns)
    sql = f"SELECT {cols} FROM {RUN_PROVENANCE_TABLE}"
    params = []
    if run_id is not None:
        sql += " WHERE run_id = ?"
        params.append(run_id)
    return [dict(zip(run_provenance_columns, row, strict=True)) for row in con.execute(sql, params).fetchall()]


def _count_rows(con, table: str) -> int:
    return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def read_corpus_state(con) -> dict | None:
    """Read the singleton corpus state, refusing duplicate rows."""
    count = _count_rows(con, CORPUS_STATE_TABLE)
    if count > 1:
        raise CorpusStateCorruptionError(f"corpus_state singleton corrupted: {count} rows present")
    row = con.execute(f"SELECT {', '.join(corpus_state_columns)} FROM {CORPUS_STATE_TABLE} LIMIT 1").fetchone()
    return dict(zip(corpus_state_columns, row, strict=True)) if row is not None else None


def update_corpus_state(
    con,
    *,
    state_version: int = 1,
    registered_song_count: int = 0,
    eligible_song_count: int = 0,
    complete_flag: bool = False,
    reconciled_at: int,
    reconciliation_status: str = "",
) -> None:
    """Upsert the singleton corpus reconciliation state transactionally."""
    con.execute("BEGIN TRANSACTION")
    try:
        count = _count_rows(con, CORPUS_STATE_TABLE)
        if count > 1:
            raise CorpusStateCorruptionError(f"corpus_state singleton corrupted: {count} rows present")
        values = {
            "state_version": state_version,
            "registered_song_count": registered_song_count,
            "eligible_song_count": eligible_song_count,
            "complete_flag": complete_flag,
            "reconciled_at": reconciled_at,
            "reconciliation_status": reconciliation_status,
        }
        if count == 0:
            _insert_row(con, CORPUS_STATE_TABLE, corpus_state_columns, values)
        else:
            con.execute(
                f"UPDATE {CORPUS_STATE_TABLE} SET {', '.join(f'{c} = ${c}' for c in corpus_state_columns)}", values
            )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


__all__ = [
    "CorpusStateCorruptionError",
    "corpus_state_columns",
    "read_corpus_state",
    "read_run_provenance",
    "run_provenance_columns",
    "update_corpus_state",
    "write_run_provenance",
]
