"""Phase 2 (P2-S4) tests for post-run provenance and corpus-state surfaces.

Covers the ``run_provenance`` + ``corpus_state`` DDL (scalar columns, no PK/UNIQUE), the
singleton update-or-insert with a corruption guard, and the embed() end-of-phase
completion that records one run row and updates the singleton.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.common import embed as embed_mod
from scripts.embedding_research.db import (
    CorpusStateCorruptionError,
    read_corpus_state,
    read_run_provenance,
    update_corpus_state,
    write_run_provenance,
)
from scripts.embedding_research.streams.store import StreamStore

RUN_PROVENANCE_EXPECTED = {
    "run_id": "VARCHAR",
    "phase": "VARCHAR",
    "status": "VARCHAR",
    "started_at": "BIGINT",
    "finished_at": "BIGINT",
    "input_artifact_hashes": "VARCHAR",
    "output_artifact_hashes": "VARCHAR",
    "config_hash": "VARCHAR",
    "song_count": "INTEGER",
    "warning_count": "INTEGER",
    "software_versions": "VARCHAR",
    "command_line": "VARCHAR",
    "structural_change_summary": "VARCHAR",
    "retained": "BOOLEAN",
    "view_refs": "VARCHAR",
}

CORPUS_STATE_EXPECTED = {
    "state_version": "INTEGER",
    "registered_song_count": "INTEGER",
    "eligible_song_count": "INTEGER",
    "complete_flag": "BOOLEAN",
    "latest_catalog_run_id": "VARCHAR",
    "reconciled_at": "BIGINT",
    "reconciliation_status": "VARCHAR",
}


def _columns(con, table: str) -> dict[str, str]:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return dict(rows)


def _constraint_kinds(con, table: str) -> list[str]:
    rows = con.execute("SELECT constraint_type FROM duckdb_constraints() WHERE table_name = ?", [table]).fetchall()
    return [r[0] for r in rows]


@pytest.mark.unit
def test_run_provenance_ddl_columns_and_types(con):
    assert _columns(con, "run_provenance") == RUN_PROVENANCE_EXPECTED


@pytest.mark.unit
def test_corpus_state_ddl_columns_and_types(con):
    assert _columns(con, "corpus_state") == CORPUS_STATE_EXPECTED


@pytest.mark.unit
@pytest.mark.parametrize("table", ["run_provenance", "corpus_state"])
def test_provenance_tables_have_no_primary_key_or_unique_constraint(con, table):
    assert "PRIMARY KEY" not in _constraint_kinds(con, table)
    assert "UNIQUE" not in _constraint_kinds(con, table)


@pytest.mark.unit
def test_write_run_provenance_appends_scalar_row(con):
    write_run_provenance(
        con,
        run_id="embed-123",
        phase="embed",
        status="complete",
        started_at=1_700_000_000_000,
        finished_at=1_700_000_000_100,
        song_count=3,
        output_artifact_hashes="abc",
    )
    rows = read_run_provenance(con, run_id="embed-123")
    assert len(rows) == 1
    assert rows[0]["phase"] == "embed"
    assert rows[0]["status"] == "complete"
    assert rows[0]["song_count"] == 3


@pytest.mark.unit
def test_corpus_state_update_or_insert_singleton(con):
    update_corpus_state(
        con,
        registered_song_count=2,
        eligible_song_count=2,
        complete_flag=True,
        reconciled_at=1_700_000_000_000,
        reconciliation_status="ok",
    )
    state = read_corpus_state(con)
    assert state is not None
    assert state["registered_song_count"] == 2
    assert state["complete_flag"] is True

    # A second update must UPDATE the existing row, never create a duplicate.
    update_corpus_state(
        con,
        registered_song_count=5,
        eligible_song_count=6,
        complete_flag=False,
        reconciled_at=1_700_000_000_200,
        reconciliation_status="partial",
    )
    state = read_corpus_state(con)
    assert state["registered_song_count"] == 5
    assert state["complete_flag"] is False
    count = con.execute("SELECT count(*) FROM corpus_state").fetchone()[0]
    assert count == 1


@pytest.mark.unit
def test_corrupt_multi_row_corpus_state_raises(con):
    con.execute(
        "INSERT INTO corpus_state (state_version, registered_song_count, eligible_song_count, complete_flag, reconciled_at) VALUES (1, 1, 1, TRUE, 1)"
    )
    con.execute(
        "INSERT INTO corpus_state (state_version, registered_song_count, eligible_song_count, complete_flag, reconciled_at) VALUES (1, 1, 1, TRUE, 1)"
    )
    with pytest.raises(CorpusStateCorruptionError):
        update_corpus_state(con, reconciled_at=2)
    with pytest.raises(CorpusStateCorruptionError):
        read_corpus_state(con)


@pytest.mark.unit
def test_embed_completion_records_run_row_and_updates_singleton(con, tmp_path):
    """embed()'s end-of-phase completion reconciles, writes one run row, updates the singleton."""
    store = StreamStore(con, output_root=tmp_path / "out")
    store.publish("song1", "effnet", np.ones((2, 3), dtype=np.float32), run_id="embed-42")
    store.reconcile()

    embed_mod._record_embed_run(
        con,
        store,
        run_id="embed-42",
        started_at=1_700_000_000_000,
        done=1,
        skipped=0,
        errors=0,
        eligible_count=1,
    )

    runs = read_run_provenance(con, run_id="embed-42")
    assert len(runs) == 1
    assert runs[0]["status"] == "complete"
    assert runs[0]["phase"] == "embed"
    assert runs[0]["song_count"] == 1
    assert runs[0]["output_artifact_hashes"]  # the published stream fingerprint

    state = read_corpus_state(con)
    assert state is not None
    assert state["registered_song_count"] == 1
    assert state["eligible_song_count"] == 1
    assert state["complete_flag"] is True
    assert state["reconciliation_status"] == "ok"


@pytest.mark.unit
def test_embed_completion_records_partial_when_errors(con, tmp_path):
    """A run with errors is recorded partial and never sets complete_flag."""
    store = StreamStore(con, output_root=tmp_path / "out")
    embed_mod._record_embed_run(
        con,
        store,
        run_id="embed-err",
        started_at=1_700_000_000_000,
        done=0,
        skipped=0,
        errors=3,
        eligible_count=4,
    )
    runs = read_run_provenance(con, run_id="embed-err")
    assert runs[0]["status"] == "partial"
    state = read_corpus_state(con)
    assert state["complete_flag"] is False
    assert state["eligible_song_count"] == 4
