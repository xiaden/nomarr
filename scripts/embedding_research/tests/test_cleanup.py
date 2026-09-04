"""Explicit cleanup/reset scopes (Plan E P3-S2) — per-scope behavior with temp DuckDB + temp dirs."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import duckdb
import pytest

from scripts.embedding_research import cleanup
from scripts.embedding_research.cleanup import (
    DEAD_DB_TABLES,
    UnclassifiedArtifactError,
    cleanup_archival_caches,
    cleanup_dead_tables,
    cleanup_staging,
    cleanup_views,
    reset_analysis_run,
    reset_cache_dirs,
    reset_db,
)
from scripts.embedding_research.db import LEGACY_RUN_ID, ensure_schema, write_analyze_metrics

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "root"


@pytest.fixture
def con():
    db = duckdb.connect(":memory:")
    db.execute("CREATE TABLE run_provenance (retained BOOLEAN, view_refs TEXT)")
    yield db
    db.close()


def _touch(p: Path, *, age_s: int = 0) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    if age_s:
        old = time.time() - age_s
        os_utime(p, old)
    return p


def os_utime(p: Path, when: float) -> None:
    import os

    os.utime(p, (when, when))


# ── staging ─────────────────────────────────────────────────────────────────────


def test_staging_removes_aged_tmp_only(root: Path) -> None:
    old = _touch(root / "s1" / ".staging" / "a.npy.tmp", age_s=7200)
    fresh = _touch(root / "s1" / ".staging" / "b.npy.tmp", age_s=1)
    # not under a .staging dir -> never touched by the staging scope
    other = _touch(root / "s1" / "c.npy.tmp")
    report = cleanup_staging(root, min_age_seconds=3600, dry_run=False)
    assert old in report.removed
    assert fresh not in report.removed  # too young -> skipped, not removed
    assert other not in report.removed  # outside .staging is a different concern
    assert old.exists() is False
    assert fresh.exists() is True
    assert other.exists() is True


def test_staging_dry_run_reports_intent_without_mutation(root: Path) -> None:
    old = _touch(root / "s1" / ".staging" / "a.npy.tmp", age_s=7200)
    report = cleanup_staging(root, min_age_seconds=3600, dry_run=True)
    assert report.dry_run is True
    assert old in report.removed  # dry_run reports what WOULD be removed
    assert old.exists() is True  # ...without mutating


def test_staging_min_age_zero_removes_all_tmp(root: Path) -> None:
    a = _touch(root / "s1" / ".staging" / "a.npy.tmp", age_s=0)
    b = _touch(root / "s2" / ".staging" / "b.npy.tmp", age_s=0)
    report = cleanup_staging(root, min_age_seconds=0, dry_run=False)
    assert {p.resolve() for p in report.removed} == {a.resolve(), b.resolve()}
    assert a.exists() is False and b.exists() is False


def test_staging_empty_dirs_ok(root: Path) -> None:
    (root / "empty" / ".staging").mkdir(parents=True)
    report = cleanup_staging(root, min_age_seconds=0, dry_run=False)
    assert report.removed == []
    assert report.skipped == []
    assert report.refused == []
    # missing root -> empty report, no error
    report2 = cleanup_staging(root / "nope", min_age_seconds=0, dry_run=False)
    assert report2.removed == []


# ── views ───────────────────────────────────────────────────────────────────────


def test_views_removes_non_retained_keeps_retained(root: Path, con) -> None:
    retained = _touch(root / "views" / "hashA" / "vectors.npy")
    disposable = _touch(root / "views" / "hashB" / "vectors.npy")
    # retained run references hashA view (keyset_hash|content_hash|view_ref)
    con.execute("INSERT INTO run_provenance VALUES (TRUE, 'hashA|cont|views/hashA')")
    report = cleanup_views(con, root, dry_run=False)
    assert retained.parent in report.skipped  # protected (retained)
    assert disposable.parent in report.removed
    assert retained.parent.exists() is True
    assert disposable.parent.exists() is False


def test_views_empty_and_no_refs_removes_all_non_retained(root: Path, con) -> None:
    # empty views root
    assert cleanup_views(con, root, dry_run=False).removed == []
    d1 = _touch(root / "views" / "h1" / "vectors.npy")
    report = cleanup_views(con, root, dry_run=False)
    assert d1.parent in report.removed


def test_views_refuses_without_db(root: Path) -> None:
    d = _touch(root / "views" / "h1" / "vectors.npy")
    report = cleanup_views(None, root, dry_run=False)
    assert report.refused  # cannot know retained refs -> refuse (no deletion)
    assert d.parent.exists() is True


def test_views_dry_run_reports_intent_without_mutation(root: Path, con) -> None:
    d = _touch(root / "views" / "h1" / "vectors.npy")
    report = cleanup_views(con, root, dry_run=True)
    assert d.parent in report.removed
    assert not report.changed
    assert d.parent.exists() is True


# ── dead ────────────────────────────────────────────────────────────────────────


def test_dead_drops_only_classified_dead_tables(con) -> None:
    # create one dead and one active table in a temp db
    con.execute("CREATE TABLE binned_calibration (backbone TEXT)")
    con.execute("CREATE TABLE analyze_metrics (strategy_key TEXT)")
    report = cleanup_dead_tables(con, tables=["binned_calibration"], dry_run=False)
    assert "binned_calibration" in report.removed
    remaining = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "binned_calibration" not in remaining
    assert "analyze_metrics" in remaining  # active table untouched


def test_dead_refuses_unclassified_table(con) -> None:
    con.execute("CREATE TABLE analyze_metrics (strategy_key TEXT)")
    with pytest.raises(UnclassifiedArtifactError):
        cleanup_dead_tables(con, tables=["analyze_metrics"], dry_run=False)
    # nothing dropped on refusal
    assert {r[0] for r in con.execute("SHOW TABLES").fetchall()} == {
        "analyze_metrics",
        "run_provenance",
    }


def test_dead_dry_run_reports_intent_without_mutation(con) -> None:
    con.execute("CREATE TABLE binned_calibration (backbone TEXT)")
    report = cleanup_dead_tables(con, tables=["binned_calibration"], dry_run=True)
    assert report.removed == ["binned_calibration"]  # dry_run reports intent
    assert not report.changed
    assert "binned_calibration" in {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def test_dead_skips_missing_table(con) -> None:
    report = cleanup_dead_tables(con, tables=["patch_features"], dry_run=False)
    assert "patch_features" in report.skipped  # DDL'd in prod schema, absent in this empty db
    assert report.removed == []


# ── archival ────────────────────────────────────────────────────────────────────


def test_archival_requires_confirmation(root: Path) -> None:
    target = _touch(root / "cache" / "binned_ptc" / "x.npz")
    report = cleanup_archival_caches(root, dry_run=False, confirm=False)
    assert report.refused  # no confirmation -> nothing removed
    assert report.removed == []
    assert target.parent.exists() is True


def test_archival_confirmed_removes(root: Path) -> None:
    target = _touch(root / "cache" / "binned_ptc" / "x.npz")
    report = cleanup_archival_caches(root, dry_run=False, confirm=True)
    assert target.parent in report.removed
    assert target.parent.exists() is False


def test_archival_refuses_unclassified_dirname(root: Path) -> None:
    _touch(root / "cache" / "flat_heads" / "x.npy")
    with pytest.raises(UnclassifiedArtifactError):
        cleanup_archival_caches(root, dirnames=["flat_heads"], confirm=True, dry_run=False)


def test_archival_dry_run_reports_intent_without_mutation(root: Path) -> None:
    target = _touch(root / "cache" / "binned_ptc" / "x.npz")
    report = cleanup_archival_caches(root, dry_run=True, confirm=True)
    assert target.parent in report.removed
    assert not report.changed
    assert target.parent.exists() is True


def test_archival_skips_missing_dirs(root: Path) -> None:
    report = cleanup_archival_caches(root, dry_run=False, confirm=True)
    assert report.removed == []


# ── reset helpers ───────────────────────────────────────────────────────────────


def test_reset_db_removes_db_and_wal_preserves_sidecars(root: Path) -> None:
    db = root / "research.duckdb"
    _touch(db)
    _touch(root / "research.duckdb.wal")
    sidecar = _touch(root / "patches" / "s1.effnet.npy")
    reset_db(db)
    assert db.exists() is False
    assert (root / "research.duckdb.wal").exists() is False
    assert sidecar.exists() is True  # immutable sidecar preserved


def test_reset_cache_dirs_binned_only_and_sidecar_preserved(root: Path) -> None:
    binned = _touch(root / "cache" / "binned_ptc" / "x.npz")
    _touch(root / "cache" / "binned_ctp" / "y.npz")
    active = _touch(root / "cache" / "effnet" / "heads" / "x.npy")  # active head cache
    reset_cache_dirs(root, binned=True)
    assert binned.parent.exists() is False
    assert (root / "cache" / "binned_ctp").exists() is False
    assert active.parent.exists() is True  # active cache never reset


def test_cleanup_scopes_are_pure_of_global_analysis_delete(con) -> None:
    """No cleanup scope reintroduces a global DELETE FROM analyze_metrics."""
    assert "analyze_metrics" in cleanup.ACTIVE_DB_TABLES
    assert "analyze_metrics" not in DEAD_DB_TABLES
    # creating analyze_metrics and running the dead scope must refuse (not delete it)
    con.execute("CREATE TABLE analyze_metrics (strategy_key TEXT)")
    with pytest.raises(UnclassifiedArtifactError):
        cleanup_dead_tables(con, tables=["analyze_metrics"], dry_run=False)
    assert {r[0] for r in con.execute("SHOW TABLES").fetchall()} == {
        "analyze_metrics",
        "run_provenance",
    }


# --------------------------------------------------------------------------- #
# P3-S3 — run-scoped analysis reset (reset_analysis_run)                        #
# --------------------------------------------------------------------------- #


def _real_schema_con():
    """A temp DB with the full Nomarr schema (analyze_metrics.run_id + run_provenance.retained)."""
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    return c


def test_reset_analysis_run_deletes_only_target_run():
    c = _real_schema_con()
    write_analyze_metrics(c, "k-a", "catalog", "cosine", 10, {"disc_general": 0.1}, run_id="run-a")
    write_analyze_metrics(c, "k-b", "catalog", "cosine", 10, {"disc_general": 0.2}, run_id="run-b")
    write_analyze_metrics(c, "k-c", "ptc", "cosine", 10, {"disc_general": 0.3}, run_id=LEGACY_RUN_ID)
    report = reset_analysis_run(c, "run-a")
    assert report.changed is True
    assert report.refused == []
    remaining = {r[0] for r in c.execute("SELECT DISTINCT run_id FROM analyze_metrics").fetchall()}
    assert remaining == {"run-b", LEGACY_RUN_ID}
    c.close()


def test_reset_analysis_run_skips_run_with_no_rows():
    c = _real_schema_con()
    report = reset_analysis_run(c, "run-missing")
    assert report.changed is False
    assert report.skipped == ["run-missing"]
    assert report.refused == []
    c.close()


def test_reset_analysis_run_refuses_legacy_without_override():
    c = _real_schema_con()
    write_analyze_metrics(c, "k", "ptc", "cosine", 10, {"disc_general": 0.3}, run_id=LEGACY_RUN_ID)
    report = reset_analysis_run(c, LEGACY_RUN_ID)
    assert report.refused == [LEGACY_RUN_ID]
    assert report.changed is False
    assert int(c.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 1
    # override=True permits the explicit reset.
    report2 = reset_analysis_run(c, LEGACY_RUN_ID, override=True)
    assert report2.refused == []
    assert int(c.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 0
    c.close()


def test_reset_analysis_run_refuses_retained_run_without_override():
    c = _real_schema_con()
    c.execute(
        "INSERT INTO run_provenance (run_id, phase, status, started_at, finished_at, song_count, "
        "warning_count, retained) VALUES ('keep-run', 'analyze', 'complete', 1, 1, 0, 0, TRUE)"
    )
    write_analyze_metrics(c, "k", "catalog", "cosine", 10, {"disc_general": 0.5}, run_id="keep-run")
    report = reset_analysis_run(c, "keep-run")
    assert report.refused == ["keep-run"]
    assert report.changed is False
    assert int(c.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 1
    # A non-retained run_id is not protected.
    report2 = reset_analysis_run(c, "keep-run", override=True)
    assert report2.refused == []
    assert int(c.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 0
    c.close()


def test_reset_analysis_run_dry_run_reports_without_mutation():
    c = _real_schema_con()
    write_analyze_metrics(c, "k", "catalog", "cosine", 10, {"disc_general": 0.5}, run_id="run-x")
    report = reset_analysis_run(c, "run-x", dry_run=True)
    assert report.changed is False
    assert report.removed != []
    assert int(c.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0]) == 1
    c.close()
