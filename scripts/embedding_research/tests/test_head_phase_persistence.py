"""Spec tests for Plan E P1-S2: canonical 18-column head-phase persistence.

The corrective pass removed legacy archival rows, the ``run_id='legacy'`` concept, the
backup-first migration and the legacy archival sinks.  ``head_phase_provenance`` is now a
pure canonical-current surface:

* canonical current rows — written by the canonical CPU runner
  (``common.head_analysis.run_shared_catalog_head_analysis``) under the exact canonical
  predicate (direct-L2 semantics only), keyed by application identity ``(config_id,
  backbone, head, bin_mode, threshold_configured, threshold_effective, semantics,
  boundary_source, head_pool_variant)`` (run_id EXCLUDED), with the duplicate-identity
  reject and the single-transaction same-identity replace.

Covers: 18-col no-PK/UNIQUE/index shape, the exact canonical predicate (direct-L2 only),
application identity, duplicate reject, same-identity rerun replace, canonical write
roundtrip, build-rows-from-manifest, and the additive guarantee that head-phase rows never
become primary analyze winners/candidates.
"""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research import db
from scripts.embedding_research.common.head_analysis import (
    BOUNDARY_SOURCE_CATALOG,
    HEAD_POOL_VARIANT,
    SCORING_SEMANTICS_VERSION,
    HeadAnalysisConfigRecord,
    HeadAnalysisManifest,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.head_phase import (
    CANONICAL_HEAD_PHASE_WHERE,
    HEAD_PHASE_PROVENANCE_COLUMNS,
    HeadPhaseProvenanceRow,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    write_head_phase_provenance,
)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _canonical_config_record(
    *,
    config_id=7,
    head="mood",
    bin_mode="temporal_global",
    threshold_configured=1.0,
    threshold_effective=1.0,
    semantics="direct_l2",
    status="done",
    reason="",
    n_songs=2,
    n_pooled=2,
    finite=True,
):
    return HeadAnalysisConfigRecord(
        config_id=config_id,
        backbone="effnet",
        head=head,
        bin_mode=bin_mode,
        threshold_configured=threshold_configured,
        threshold_effective=threshold_effective,
        semantics=semantics,
        status=status,
        reason=reason,
        n_songs=n_songs,
        n_pooled=n_pooled,
        finite=finite,
        boundary_source=BOUNDARY_SOURCE_CATALOG,
        head_pool_variant=HEAD_POOL_VARIANT,
    )


def _canonical_manifest(run_id="run-canonical", *, results=None, **overrides):
    results = results or (_canonical_config_record(),)
    fields = {
        "run_id": run_id,
        "config_ids": tuple(sorted({r.config_id for r in results})),
        "boundary_source": BOUNDARY_SOURCE_CATALOG,
        "head_pool_variant": HEAD_POOL_VARIANT,
        "backbones": ("effnet",),
        "heads": tuple(sorted({r.head for r in results})),
        "song_ids": ("s1", "s2"),
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "results": tuple(results),
        "skip_reasons": (),
        "done": sum(1 for r in results if r.status == "done"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "errors": sum(1 for r in results if r.status == "error"),
        "finite": all(r.finite for r in results),
    }
    fields.update(overrides)
    return HeadAnalysisManifest(**fields)


def _canonical_row(**overrides):
    base = {
        "run_id": "run-canonical",
        "config_id": 7,
        "backbone": "effnet",
        "head": "mood",
        "bin_mode": "temporal_global",
        "threshold_configured": 1.0,
        "threshold_effective": 1.0,
        "semantics": "direct_l2",
        "boundary_source": BOUNDARY_SOURCE_CATALOG,
        "head_pool_variant": HEAD_POOL_VARIANT,
        "status": "done",
        "reason": None,
        "n_songs": 2,
        "n_pooled": 2,
        "finite": True,
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "reference_corpus_hash": "hash-primary",
        "threshold": None,
    }
    base.update(overrides)
    return HeadPhaseProvenanceRow(**base)


def _identity_of(row):
    return head_phase_config_key(
        config_id=row.config_id,
        backbone=row.backbone,
        head=row.head,
        bin_mode=row.bin_mode,
        threshold_configured=row.threshold_configured,
        threshold_effective=row.threshold_effective,
        semantics=row.semantics,
        boundary_source=row.boundary_source,
        head_pool_variant=row.head_pool_variant,
    )


# ---------------------------------------------------------------------------
# P1-S2: 18-column superset, no PK, exact canonical predicate
# ---------------------------------------------------------------------------


def test_head_phase_table_is_18_column_no_pk(con):
    """Table is the EXACT 18-column no-constraint DDL."""
    cols = [r[1] for r in con.execute("PRAGMA table_info('head_phase_provenance')").fetchall()]
    assert cols == list(HEAD_PHASE_PROVENANCE_COLUMNS)
    # No primary key / unique / index.
    pk = con.execute(
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE table_name='head_phase_provenance' AND constraint_type IN ('PRIMARY KEY','UNIQUE')"
    ).fetchone()[0]
    assert pk == 0
    indexes = con.execute("SELECT count(*) FROM duckdb_indexes() WHERE table_name='head_phase_provenance'").fetchone()[
        0
    ]
    assert indexes == 0


def test_canonical_predicate_is_direct_l2_only():
    """The canonical predicate admits only canonical direct-L2 EffNet shared-boundary rows."""
    assert "config_id IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "backbone = 'effnet'" in CANONICAL_HEAD_PHASE_WHERE
    assert "bin_mode IN ('temporal_global', 'temporal_perdim')" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold_configured IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold_effective IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "semantics IN ('direct_l2')" in CANONICAL_HEAD_PHASE_WHERE
    assert "boundary_source = 'catalog'" in CANONICAL_HEAD_PHASE_WHERE
    assert "head_pool_variant = 'shared_catalog_boundary'" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold IS NULL" in CANONICAL_HEAD_PHASE_WHERE
    # std_scaled / legacy vocabulary is gone from the canonical surface.
    assert "std_scaled" not in CANONICAL_HEAD_PHASE_WHERE
    assert "legacy" not in CANONICAL_HEAD_PHASE_WHERE


# ---------------------------------------------------------------------------
# P1-S2: canonical writes — dup reject, same-identity replace
# ---------------------------------------------------------------------------


def test_write_head_phase_provenance_roundtrip(con):
    write_head_phase_provenance(con, [_canonical_row()])
    loaded = load_head_phase_provenance(con)
    assert len(loaded) == 1
    got = loaded[0]
    assert got.config_id == 7
    assert got.head == "mood"
    assert got.bin_mode == "temporal_global"
    assert got.threshold_configured == pytest.approx(1.0)
    assert got.threshold_effective == pytest.approx(1.0)
    assert got.semantics == "direct_l2"
    assert got.threshold is None
    assert got.run_id == "run-canonical"
    # canonical fields non-NULL; legacy threshold column NULL for canonical rows.
    assert got.config_id is not None


def test_write_uses_named_18_column_insert(con):
    captured = {}

    class _Recorder:
        def execute(self, sql, params=None):
            return con.execute(sql, params)

        def executemany(self, sql, params=None):
            captured["sql"] = sql
            return con.executemany(sql, params or [])

    write_head_phase_provenance(_Recorder(), [_canonical_row()])
    assert captured["sql"].count("?") == 18
    for col in HEAD_PHASE_PROVENANCE_COLUMNS:
        assert f"{col}" in captured["sql"]


def test_duplicate_canonical_identity_rejected_in_one_batch(con):
    """Two canonical rows sharing one identity in a single write are rejected."""
    rows = [
        _canonical_row(run_id="r1", n_pooled=2),
        _canonical_row(run_id="r2", n_pooled=2),  # same identity, different run_id
    ]
    with pytest.raises(ValueError, match="duplicate canonical head-phase identity"):
        write_head_phase_provenance(con, rows)
    # Nothing persisted (the batch failed closed).
    assert load_head_phase_provenance(con) == []


def test_same_identity_rerun_replaces_in_one_transaction(con):
    """A rerun with the same identity replaces the prior current row only."""
    write_head_phase_provenance(con, [_canonical_row(run_id="r1", n_pooled=2)])
    write_head_phase_provenance(con, [_canonical_row(run_id="r2", n_pooled=2)])
    rows = load_head_phase_provenance(con)
    # Exactly one current canonical row for the identity — never two.
    assert len(rows) == 1
    assert rows[0].run_id == "r2"
    assert rows[0].n_pooled == 2
    # Only one physical row remains (prior current row replaced).
    assert con.execute("SELECT count(*) FROM head_phase_provenance").fetchone()[0] == 1


def test_write_rejects_noncanonical_unclassified_row(con):
    """Unclassified rows fail closed — never silently persisted."""
    with pytest.raises(ValueError):
        write_head_phase_provenance(con, [_canonical_row(semantics="ctp")])


def test_write_validates_finite_and_counts(con):
    bad = [
        _canonical_row(threshold_configured=float("nan")),
        _canonical_row(n_songs=-1),
        _canonical_row(n_pooled=5, n_songs=3),
    ]
    for row in bad:
        with pytest.raises(ValueError):
            write_head_phase_provenance(con, [row])
    assert load_head_phase_provenance(con) == []


# ---------------------------------------------------------------------------
# P1-S2: canonical identity excludes run_id
# ---------------------------------------------------------------------------


def test_head_phase_config_key_excludes_run_id():
    k1 = _identity_of(_canonical_row(run_id="r1"))
    k2 = _identity_of(_canonical_row(run_id="r2"))
    assert k1 == k2  # application identity ignores run_id
    assert k1.startswith("head:")
    assert k1 == ("head:7:effnet:mood:temporal_global:1.0:1.0:direct_l2:catalog:shared_catalog_boundary")
    # Different heads / configs / semantics are distinct identities.
    assert _identity_of(_canonical_row(head="timbre")) != k1
    assert _identity_of(_canonical_row(config_id=9)) != k1
    assert _identity_of(_canonical_row(threshold_configured=1.1)) != k1


def test_head_phase_identity_not_an_analyze_strategy_key():
    assert _identity_of(_canonical_row()).split(":")[0] == "head"
    assert not _identity_of(_canonical_row()).startswith(("ptc:", "ctp:", "global_pool:"))


# ---------------------------------------------------------------------------
# P1-S2: build canonical rows from the HeadAnalysisManifest
# ---------------------------------------------------------------------------


def test_build_rows_from_canonical_manifest():
    rec = _canonical_config_record(head="mood", n_pooled=2)
    manifest = _canonical_manifest(run_id="r-canon", results=(rec,))
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash="h")
    assert len(rows) == 1
    r = rows[0]
    assert r.run_id == "r-canon"
    assert r.config_id == 7
    assert r.threshold is None
    assert r.threshold_configured == pytest.approx(1.0)
    assert r.threshold_effective == pytest.approx(1.0)
    assert r.semantics == "direct_l2"
    assert r.boundary_source == BOUNDARY_SOURCE_CATALOG
    assert r.head_pool_variant == HEAD_POOL_VARIANT
    assert r.status == "done" and r.n_songs == 2 and r.n_pooled == 2
    assert r.reference_corpus_hash == "h"


def test_head_phase_provenance_additive_does_not_touch_analyze_metrics(con):
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_canonical_manifest()))
    assert db.query_analysis_done(con) == set()
    assert con.execute("SELECT * FROM analyze_metrics").fetchall() == []


def test_head_phase_rows_never_primary_winner_candidate(con):
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_canonical_manifest()))
    assert db.query_analysis_done(con) == set()
    assert con.execute("SELECT strategy_key, strategy_type FROM analyze_metrics").fetchall() == []
    for r in load_head_phase_provenance(con):
        assert r.config_key.startswith("head:")
        assert r.config_key.split(":")[0] == "head"


def test_head_phase_rows_carry_integer_ms_run_id(con):
    """Canonical rows carry an integer-millisecond run identity (no legacy concept)."""
    rec = _canonical_config_record(head="mood")
    manifest = _canonical_manifest(run_id="head-analysis-1700000000000", results=(rec,))
    rows = build_head_phase_provenance_rows(manifest)
    assert rows[0].run_id == "head-analysis-1700000000000"
    write_head_phase_provenance(con, rows)
    got = load_head_phase_provenance(con)[0]
    assert got.run_id == "head-analysis-1700000000000"
