"""Plan E P4-S4 — post-crash rollback-only canary over surviving PK/UNIQUE tables.

DD "Post-crash verification canary": before any ``catalog`` / ``analyze`` /
``report`` read — after a detected post-crash condition, or when ``--verify``
requests it — a rollback-only canary probes EVERY surviving table with a
``PRIMARY KEY`` or ``UNIQUE`` constraint.  The inventory is enumerated from
DuckDB metadata at runtime (``duckdb_constraints()``) — never hardcoded as a
permanent list.  Empty tables are recorded ``empty`` (NOT corrupt: CTP-disabled
empty tables are expected).  A non-empty table's lexicographically-smallest key
row is captured in full, deleted by key, re-inserted, and the transaction is
ROLLED BACK unconditionally — probe writes are NEVER committed.  Any failure
(delete-count mismatch, insert/index/constraint failure, any probe exception)
raises :class:`CanaryCorruptionError`, which blocks the read and demands repair
with ``EXPORT DATABASE`` then ``IMPORT DATABASE`` into a fresh DuckDB file.

Trigger wiring (tested here): the canary runs (i) when ``--verify``/``--strict``
requests it for a derived phase, and (ii) on a detected post-crash condition
(a surviving ``.wal`` file, or a non-``completed`` ``run_provenance`` row) before
any derived-phase read.  A clean run WITHOUT ``--verify`` pays no probe cost
(beyond the cheap post-crash detection check).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db import canary

# The legacy/active tables in db/_schema.py that declare a PRIMARY KEY / UNIQUE.
# Used ONLY as a static expectation log; the canary's runtime inventory is never
# hardcoded — it is enumerated from duckdb_constraints() at runtime.
_EXPECTED_PK_UNIQUE_TABLES = frozenset(
    {
        "songs",
        "pooled_vecs",
        "head_results",
        "binned_calibration",
        "head_agreement_rows",
        "patch_features",
        "binned_pair_sims",
        "binned_song_stats",
        "binned_classify_ctp",
        "truncation_robustness_rows",
        "binned_ctp_vecs",
        "binned_ptc_ctp_metrics",
        "head_sim_corr_rows",
        "phase_timings",
        "stratified_corpus",
        "song_retrieval_metrics",
    }
)

# Active tables deliberately WITHOUT any PK/UNIQUE must never appear in the probe set.
_EXPECTED_NO_PK_TABLES = {
    "stream_registry",
    "head_stream_registry",
    "run_provenance",
    "seg_config",
    "seg_meta",
    "seg_membership",
    "head_phase_provenance",
    "analyze_metrics",
    "catalog_metadata",
}


# --------------------------------------------------------------------------- #
# Runtime inventory enumeration (not a hardcoded permanent list)              #
# --------------------------------------------------------------------------- #


def test_canary_enumerates_every_pk_unique_table_from_duckdb_metadata(con):
    tables = {t for t, _cols in canary.enumerate_pk_unique_tables(con)}
    assert tables >= _EXPECTED_PK_UNIQUE_TABLES, _EXPECTED_PK_UNIQUE_TABLES - tables
    # the no-PK tables are deliberately excluded from the probe set.
    assert tables.isdisjoint(_EXPECTED_NO_PK_TABLES)


def test_canary_enumerates_key_columns(con):
    inv = dict(canary.enumerate_pk_unique_tables(con))
    assert inv["songs"] == ("song_id",)
    assert set(inv["stratified_corpus"]) == {"config_hash", "song_id"}
    assert set(inv["phase_timings"]) == {"run_ts", "phase"}


# --------------------------------------------------------------------------- #
# Empty table -> 'empty', never corrupt                                       #
# --------------------------------------------------------------------------- #


def test_empty_tables_recorded_empty_not_corrupt(con):
    report = canary.run_rollback_canary(con)
    assert report.failed is False
    assert set(report.tables) == _EXPECTED_PK_UNIQUE_TABLES
    assert len(report.empty) == len(_EXPECTED_PK_UNIQUE_TABLES)
    assert report.ok == []


# --------------------------------------------------------------------------- #
# Non-empty sentinel delete/re-insert/rollback is byte-identical + never       #
# commits                                                                     #
# --------------------------------------------------------------------------- #


def _seed_row(con, table: str, columns: list, row: list) -> None:
    keys = ", ".join(f'"{c}"' for c in columns)
    ph = ", ".join("?" for _ in columns)
    con.execute(f"INSERT INTO {table} ({keys}) VALUES ({ph})", row)


def test_canary_probe_rolls_back_and_leaves_rows_unchanged(con):
    # songs (single-col PK), phase_timings (composite PK), binned_calibration (PK),
    # pooled_vecs (FLOAT[] vector column round-trips through capture/re-insert).
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sX", "/audio/sX.mp3", "Z"])
    _seed_row(con, "phase_timings", ["run_ts", "phase", "elapsed_s"], ["ts1", "analyze", 1.5])
    _seed_row(con, "binned_calibration", ["backbone", "dist_mode", "n_patches"], ["effnet", "direct_l2", 3])
    _seed_row(
        con,
        "pooled_vecs",
        ["song_id", "backbone", "strategy", "vec"],
        ["sX", "effnet", "global_pool", np.arange(6, dtype=np.float32).tolist()],
    )
    before = {
        t: con.execute(f"SELECT * FROM {t}").fetchall()
        for t in ("songs", "phase_timings", "binned_calibration", "pooled_vecs")
    }

    report = canary.run_rollback_canary(con)

    assert report.tables["songs"] == "ok"
    assert report.tables["phase_timings"] == "ok"
    assert report.tables["binned_calibration"] == "ok"
    assert report.tables["pooled_vecs"] == "ok"
    # Rolled back unconditionally: every seeded row is still present, byte-identical.
    for table, rows in before.items():
        assert con.execute(f"SELECT * FROM {table}").fetchall() == rows, table
    # No side-effect duplicates from a committed re-insert.
    n = con.execute("SELECT count(*) FROM songs").fetchone()[0]
    assert n == 1


def test_canary_delete_reinsert_happens_inside_tx_and_is_rolled_back(con, monkeypatch):
    """The delete+re-insert both execute inside the transaction, then ROLL BACK.

    We observe the seam directly: while the sentinel re-insert runs (still inside the
    open transaction, before the unconditional ROLLBACK), the sentinel is absent then
    re-present; after the canary returns the table is unchanged.
    """
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sY", "/audio/sY.mp3", "Q"])
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sZ", "/audio/sZ.mp3", "R"])
    real_insert = canary._insert_sentinel
    observed: dict[str, list] = {"during_insert": [], "post_delete": []}
    real_delete = canary._delete_sentinel

    def _watch_delete(con_, table, key_cols, key_vals):
        n = real_delete(con_, table, key_cols, key_vals)
        # Immediately after DELETE, inside the open tx, the sentinel must be gone.
        if table == "songs":
            observed["post_delete"].append(con_.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        return n

    def _watch_insert(con_, table, columns, values):
        real_insert(con_, table, columns, values)
        if table == "songs":
            # Still inside the tx: delete made the sentinel vanish; re-insert restores it.
            observed["during_insert"].append(con_.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        return

    monkeypatch.setattr(canary, "_delete_sentinel", _watch_delete)
    monkeypatch.setattr(canary, "_insert_sentinel", _watch_insert)

    canary.run_rollback_canary(con)

    # songs: lexicographically smallest (sY) sentinel. post_delete saw count 1 (only sZ),
    # then during_insert saw 2 (sY restored inside the tx). After rollback both remain.
    assert observed["post_delete"] == [1], observed
    assert observed["during_insert"] == [2], observed
    rows = con.execute("SELECT song_id FROM songs ORDER BY song_id").fetchall()
    assert rows == [("sY",), ("sZ",)]


# --------------------------------------------------------------------------- #
# Failure -> CanaryCorruptionError with EXPORT/IMPORT repair guidance         #
# --------------------------------------------------------------------------- #


def test_delete_count_mismatch_raises_canary_failure_with_repair_text(con, monkeypatch):
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sA", "/audio/sA.mp3", "A"])
    monkeypatch.setattr(canary, "_delete_sentinel", lambda *_a, **_k: 0)  # deleted 0, expected 1

    with pytest.raises(canary.CanaryCorruptionError) as exc:
        canary.run_rollback_canary(con)

    msg = str(exc.value)
    assert "delete-count mismatch" in msg
    assert "EXPORT DATABASE" in msg and "IMPORT DATABASE" in msg
    assert "canary blocked" in msg.lower() or "repair" in msg.lower()
    # probe never committed the delete — the row is still present.
    assert con.execute("SELECT count(*) FROM songs").fetchone()[0] == 1


def test_constraint_insert_failure_raises_canary_failure_with_repair_text(con, monkeypatch):
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sB", "/audio/sB.mp3", "B"])
    monkeypatch.setattr(
        canary, "_insert_sentinel", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("forced insert failure"))
    )

    with pytest.raises(canary.CanaryCorruptionError) as exc:
        canary.run_rollback_canary(con)

    msg = str(exc.value)
    assert "probe failed" in msg
    assert "EXPORT DATABASE" in msg and "IMPORT DATABASE" in msg
    assert con.execute("SELECT count(*) FROM songs").fetchone()[0] == 1  # rolled back


# --------------------------------------------------------------------------- #
# Failure blocks the phase read (wired through the --verify gate)             #
# --------------------------------------------------------------------------- #


def test_canary_failure_blocks_a_verify_phase(con, tmp_path, monkeypatch):
    _seed_row(con, "songs", ["song_id", "path", "artist"], ["sC", "/audio/sC.mp3", "C"])
    monkeypatch.setattr(canary, "_delete_sentinel", lambda *_a, **_k: 0)

    cfg = {
        "verify": True,
        "strict": True,
        "retained": False,
        "force": False,
        "output_root": str(tmp_path / "out"),
        "report_dir": str(tmp_path / "out" / "report"),
        "run_id": None,
        "config_hash": "testcfg",
    }
    with pytest.raises(canary.CanaryCorruptionError) as exc:
        run_mod._run_single_phase(con, "catalog-report", cfg, db_path=None)

    assert "EXPORT DATABASE" in str(exc.value) and "IMPORT DATABASE" in str(exc.value)
    # the blocked phase was recorded as failed provenance.
    row = con.execute(
        "SELECT phase, status FROM run_provenance WHERE phase='catalog-report' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None and row[1] == "failed"


# --------------------------------------------------------------------------- #
# Trigger wiring: post-crash detection + clean-run no-probe cost              #
# --------------------------------------------------------------------------- #


def test_post_crash_detected_from_surviving_wal_file(con, tmp_path):
    db_path = tmp_path / "research.db"
    assert canary.detect_post_crash(con, db_path=db_path) is False  # no .wal yet
    # simulate an unclean prior close: a surviving .wal next to the db file.
    Path(str(db_path) + ".wal").touch()
    assert canary.detect_post_crash(con, db_path=db_path) is True


def test_post_crash_detected_from_non_completed_run_provenance(con):
    assert canary.detect_post_crash(con, db_path=None) is False
    con.execute(
        "INSERT INTO run_provenance (run_id, phase, status, started_at, song_count, warning_count) "
        "VALUES ('r1', 'analyze', 'failed', 1, 0, 0)"
    )
    assert canary.detect_post_crash(con, db_path=None) is True


def test_clean_run_without_verify_does_not_invoke_probes(con, monkeypatch):
    """No --verify and no post-crash signal => thin gate: canary is NOT probed."""
    calls: list[str] = []

    def _spy_run_rollback_canary(*_a, **_k):
        calls.append("run_rollback_canary")
        raise AssertionError("canary must not run on a clean non-verify run")

    monkeypatch.setattr(canary, "run_rollback_canary", _spy_run_rollback_canary)
    cfg = {"verify": False, "strict": False}

    notes = run_mod._preflight_derived_phase(con, "catalog-report", cfg, db_path=None)

    assert notes == []  # thin gate: nothing to verify, no probe cost
    assert calls == []


def test_post_crash_signal_triggers_canary_even_without_verify(con, tmp_path, monkeypatch):
    """A detected post-crash state runs the rollback-only canary even with NO --verify.

    run.py L1308-1310: ``post_crash = detect_post_crash(...)`` then
    ``if not verify and not post_crash: return []``.  A surviving ``.wal`` (db_path
    supplied) or a non-``completed`` run_provenance row (db_path=None) makes
    ``post_crash`` True, so the canary runs without ever being requested by --verify.
    """
    calls: list[str] = []

    def _spy(*_a, **_k):
        calls.append("run_rollback_canary")
        return canary.CanaryProbeReport()

    monkeypatch.setattr(canary, "run_rollback_canary", _spy)
    cfg = {"verify": False, "strict": False}

    # Scenario A: a surviving .wal next to the db file signals a post-crash state.
    db_path = tmp_path / "research.db"
    Path(str(db_path) + ".wal").touch()
    run_mod._preflight_derived_phase(con, "catalog-report", cfg, db_path=db_path)
    assert calls == ["run_rollback_canary"]  # wal alone triggered the probe

    # Scenario B: a non-completed run_provenance row also signals post-crash and
    # triggers the probe even with db_path=None (nothing to inspect on disk).
    con.execute(
        "INSERT INTO run_provenance (run_id, phase, status, started_at, song_count, warning_count) "
        "VALUES ('r1', 'analyze', 'failed', 1, 0, 0)"
    )
    run_mod._preflight_derived_phase(con, "catalog-report", cfg, db_path=None)
    assert calls == ["run_rollback_canary", "run_rollback_canary"]


def test_verify_invokes_canary_and_blocks_are_distinct_from_post_crash(con, monkeypatch):
    """--verify forces the canary even on a clean connection (no post-crash signal)."""
    calls: list[str] = []

    def _spy(*_a, **_k):
        calls.append("run_rollback_canary")
        from scripts.embedding_research.db.canary import CanaryProbeReport

        return CanaryProbeReport()

    monkeypatch.setattr(canary, "run_rollback_canary", _spy)
    cfg = {"verify": True, "strict": False}

    notes = run_mod._preflight_derived_phase(con, "catalog-report", cfg, db_path=None)

    assert calls == ["run_rollback_canary"]  # verify forced the probe
    assert any("canary ok:" in n for n in notes)
