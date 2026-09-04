"""Spec-first tests for Plan E, Phase 1 (P1-S3/S1-S4): canonical 18-column persistence.

The head-phase provenance table was migrated (D2) from the legacy 13-column model
with a 6-column PK to an EXACT 18-column, no-PK/no-UNIQUE/no-index table whose
named-column writes distinguish:

* canonical current rows — written by the canonical CPU runner under the D3
  predicate, keyed by application identity ``(config_id, backbone, head, bin_mode,
  threshold_configured, threshold_effective, semantics, boundary_source,
  head_pool_variant)`` (run_id EXCLUDED), with the duplicate-identity reject and
  the single-transaction same-identity replace;
* legacy archival rows — ``run_id='legacy'``, threshold populated, canonical-only
  fields NULL, appended only (never updated/active/converted).

Covers: 18-col superset + PK removal, backup-first migration preserving every
legacy row verbatim, the D3 predicate, application identity, duplicate reject,
same-identity rerun replace, archival preservation, the canonical runner's
coverage/skip writes, and the LEGACY run.py glue that appends archival-only rows.
"""

from __future__ import annotations

import logging

import duckdb
import pytest

import scripts.embedding_research.classify as classify_mod
from scripts.embedding_research import db
from scripts.embedding_research import run as run_mod
from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.common.head_analysis import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HEAD_POOL_VARIANT,
    HeadPhaseConfigRecord,
    HeadPhaseManifest,
)
from scripts.embedding_research.corpus import MatchingCorpusManifest
from scripts.embedding_research.db._schema import ensure_schema, migrate_head_phase_provenance
from scripts.embedding_research.db.head_phase import (
    CANONICAL_HEAD_PHASE_WHERE,
    HEAD_PHASE_PROVENANCE_COLUMNS,
    LEGACY_RUN_ID,
    HeadPhaseProvenanceRow,
    append_head_phase_archival_rows,
    build_archival_provenance_rows,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    is_canonical_row,
    load_head_phase_provenance,
    load_head_phase_provenance_all,
    query_head_phase_done,
    write_head_phase_provenance,
)
from scripts.embedding_research.head_pooling import HeadPhaseConfigRecord as LegacyHeadPhaseConfigRecord
from scripts.embedding_research.head_pooling import HeadPhaseManifest as LegacyHeadPhaseManifest


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
    return HeadPhaseConfigRecord(
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
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        head_pool_variant=HEAD_POOL_VARIANT,
    )


def _canonical_manifest(run_id="run-canonical", *, results=None, **overrides):
    results = results or (_canonical_config_record(),)
    fields = {
        "run_id": run_id,
        "config_ids": tuple(sorted({r.config_id for r in results})),
        "dimensions": (1280,),
        "boundary_source": BOUNDARY_SOURCE_EFFNET_PTC,
        "head_pool_variant": HEAD_POOL_VARIANT,
        "backbones": ("effnet",),
        "heads": tuple(sorted({r.head for r in results})),
        "bin_modes": tuple(sorted({r.bin_mode for r in results})),
        "song_ids": ("s1", "s2"),
        "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
        "results": tuple(results),
        "skip_reasons": (),
        "done": sum(1 for r in results if r.status == "done"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "errors": sum(1 for r in results if r.status == "error"),
        "finite": all(r.finite for r in results),
        "reference_corpus_hash": None,
        "primary_analysis_succeeded": True,
    }
    fields.update(overrides)
    return HeadPhaseManifest(**fields)


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
        "boundary_source": BOUNDARY_SOURCE_EFFNET_PTC,
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
# P1-S3: 18-column superset, PK removal, exact D3 predicate
# ---------------------------------------------------------------------------


def test_head_phase_table_is_18_column_no_pk(con):
    """Post-migration table is the EXACT 18-column no-constraint DDL (D2)."""
    cols = [r[1] for r in con.execute("PRAGMA table_info('head_phase_provenance')").fetchall()]
    assert cols == list(HEAD_PHASE_PROVENANCE_COLUMNS)
    # No primary key / unique / index survive the migration.
    pk = con.execute(
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE table_name='head_phase_provenance' AND constraint_type IN ('PRIMARY KEY','UNIQUE')"
    ).fetchone()[0]
    assert pk == 0
    indexes = con.execute("SELECT count(*) FROM duckdb_indexes() WHERE table_name='head_phase_provenance'").fetchone()[
        0
    ]
    assert indexes == 0


def test_canonical_predicate_is_exact_d3_sql():
    """The canonical predicate is the exact D3 WHERE clause (no silent widening)."""
    assert "run_id <> 'legacy'" in CANONICAL_HEAD_PHASE_WHERE
    assert "config_id IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "backbone = 'effnet'" in CANONICAL_HEAD_PHASE_WHERE
    assert "bin_mode IN ('temporal_global', 'temporal_perdim')" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold_configured IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold_effective IS NOT NULL" in CANONICAL_HEAD_PHASE_WHERE
    assert "semantics IN ('direct_l2', 'std_scaled')" in CANONICAL_HEAD_PHASE_WHERE
    assert "boundary_source = 'effnet_ptc'" in CANONICAL_HEAD_PHASE_WHERE
    assert "head_pool_variant = 'shared_effnet_ptc_boundary'" in CANONICAL_HEAD_PHASE_WHERE
    assert "threshold IS NULL" in CANONICAL_HEAD_PHASE_WHERE


def test_is_canonical_row_matches_predicate():
    assert is_canonical_row(_canonical_row()) is True
    assert (
        is_canonical_row(
            _canonical_row(
                run_id=LEGACY_RUN_ID,
                threshold=1.0,
                config_id=None,
                threshold_configured=None,
                threshold_effective=None,
                semantics=None,
            )
        )
        is False
    )
    assert is_canonical_row(_canonical_row(semantics="ctp")) is False
    assert is_canonical_row(_canonical_row(bin_mode="temporal_half")) is False
    assert is_canonical_row(_canonical_row(boundary_source="ctp")) is False
    assert is_canonical_row(_canonical_row(config_id=None)) is False
    assert is_canonical_row(_canonical_row(threshold=1.0)) is False


# ---------------------------------------------------------------------------
# P1-S3: backup-first migration preserves every legacy row verbatim
# ---------------------------------------------------------------------------


def _create_legacy_table(con):
    con.execute(
        """CREATE TABLE head_phase_provenance (
            backbone                  TEXT NOT NULL,
            head                      TEXT NOT NULL,
            bin_mode                  TEXT NOT NULL,
            threshold                 DOUBLE NOT NULL,
            boundary_source           TEXT NOT NULL,
            head_pool_variant         TEXT NOT NULL,
            status                    TEXT NOT NULL,
            reason                    TEXT,
            n_songs                   INTEGER NOT NULL,
            n_pooled                  INTEGER NOT NULL,
            finite                    INTEGER NOT NULL,
            scoring_semantics_version INTEGER NOT NULL,
            reference_corpus_hash     TEXT,
            PRIMARY KEY (backbone, head, bin_mode, threshold, boundary_source, head_pool_variant)
        )"""
    )


def test_migration_backup_first_preserves_legacy_rows_verbatim():
    """D2 migration: backup-first, one transactional create-copy-drop-rename."""
    c = duckdb.connect(":memory:")
    try:
        _create_legacy_table(c)
        c.execute(
            "INSERT INTO head_phase_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "effnet",
                "genre",
                "temporal_global",
                1.0,
                "effnet_ptc",
                "shared_effnet_ptc_boundary",
                "done",
                None,
                5,
                5,
                1,
                4,
                "abc123",
            ],
        )
        c.execute(
            "INSERT INTO head_phase_provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "effnet",
                "mood_happy",
                "temporal_perdim",
                1.1,
                "effnet_ptc",
                "shared_effnet_ptc_boundary",
                "skipped",
                "legacy reason",
                3,
                0,
                1,
                4,
                None,
            ],
        )
        migrated = migrate_head_phase_provenance(c)
        assert migrated == 2

        all_rows = load_head_phase_provenance_all(c)
        assert len(all_rows) == 2
        for row in all_rows:
            assert row.run_id == LEGACY_RUN_ID
            assert row.config_id is None
            assert row.threshold_configured is None
            assert row.threshold_effective is None
            assert row.semantics is None
            assert row.boundary_source == "effnet_ptc"
            assert row.head_pool_variant == "shared_effnet_ptc_boundary"
        by_head = {r.head: r for r in all_rows}
        # Old threshold + provenance retained verbatim.
        assert by_head["genre"].threshold == pytest.approx(1.0)
        assert by_head["genre"].n_songs == 5 and by_head["genre"].n_pooled == 5
        assert by_head["genre"].scoring_semantics_version == 4
        assert by_head["genre"].reference_corpus_hash == "abc123"
        assert by_head["mood_happy"].reason == "legacy reason"
        assert by_head["mood_happy"].threshold == pytest.approx(1.1)
        # Legacy rows are NOT canonical coverage.
        assert load_head_phase_provenance(c) == []
        # Backup-first copy exists.
        n_backup = c.execute("SELECT count(*) FROM head_phase_provenance_backup").fetchone()[0]
        assert n_backup == 2
        cols = [r[1] for r in c.execute("PRAGMA table_info('head_phase_provenance')").fetchall()]
        assert cols == list(HEAD_PHASE_PROVENANCE_COLUMNS)
    finally:
        c.close()


def test_migration_is_noop_when_table_absent():
    c = duckdb.connect(":memory:")
    try:
        assert migrate_head_phase_provenance(c) == 0
    finally:
        c.close()


# ---------------------------------------------------------------------------
# P1-S3: canonical writes — dup reject, same-identity replace, archival untouched
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
    assert is_canonical_row(got)


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
    """Two canonical rows sharing one identity in a single write are rejected (D3)."""
    rows = [
        _canonical_row(run_id="r1", n_pooled=2),
        _canonical_row(run_id="r2", n_pooled=2),  # same identity, different run_id
    ]
    with pytest.raises(ValueError, match="duplicate canonical head-phase identity"):
        write_head_phase_provenance(con, rows)
    # Nothing persisted (the batch failed closed).
    assert load_head_phase_provenance(con) == []


def test_same_identity_rerun_replaces_in_one_transaction(con):
    """A rerun with the same identity replaces the prior current row only (D3)."""
    write_head_phase_provenance(con, [_canonical_row(run_id="r1", n_pooled=2)])
    write_head_phase_provenance(con, [_canonical_row(run_id="r2", n_pooled=2)])
    rows = load_head_phase_provenance(con)
    # Exactly one current canonical row for the identity — never two.
    assert len(rows) == 1
    assert rows[0].run_id == "r2"
    assert rows[0].n_pooled == 2
    # Only one physical row remains (prior current row replaced).
    assert con.execute("SELECT count(*) FROM head_phase_provenance").fetchone()[0] == 1


def test_write_rejects_legacy_archival_row(con):
    """Canonical rows are written ONLY by the canonical writer; legacy rows rejected (D1)."""
    legacy = _canonical_row(
        run_id=LEGACY_RUN_ID,
        threshold=1.0,
        config_id=None,
        threshold_configured=None,
        threshold_effective=None,
        semantics=None,
    )
    with pytest.raises(ValueError, match="legacy archival"):
        write_head_phase_provenance(con, [legacy])


def test_archival_rows_appended_and_never_replaced(con):
    """append_head_phase_archival_rows appends legacy rows; canonical writes leave them alone (D1)."""
    legacy = HeadPhaseProvenanceRow(
        run_id=LEGACY_RUN_ID,
        backbone="effnet",
        head="mood",
        bin_mode="temporal_global",
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        head_pool_variant=HEAD_POOL_VARIANT,
        status="done",
        reason=None,
        n_songs=3,
        n_pooled=3,
        finite=True,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        reference_corpus_hash=None,
        threshold=0.9,
    )
    append_head_phase_archival_rows(con, [legacy])
    write_head_phase_provenance(con, [_canonical_row()])  # same head, canonical identity
    all_rows = load_head_phase_provenance_all(con)
    assert len(all_rows) == 2
    legacy_rows = [r for r in all_rows if r.run_id == LEGACY_RUN_ID]
    assert len(legacy_rows) == 1
    assert legacy_rows[0].threshold == pytest.approx(0.9)
    assert legacy_rows[0].config_id is None
    # Canonical load sees only the canonical current row.
    canon = load_head_phase_provenance(con)
    assert len(canon) == 1 and canon[0].run_id != LEGACY_RUN_ID


def test_append_archival_rejects_canonical_row(con):
    with pytest.raises(ValueError):
        append_head_phase_archival_rows(con, [_canonical_row()])


def test_write_rejects_noncanonical_unclassified_row(con):
    """Unclassified rows fail closed — never silently persisted (D3)."""
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
# P1-S3: canonical identity excludes run_id
# ---------------------------------------------------------------------------


def test_head_phase_config_key_excludes_run_id():
    k1 = _identity_of(_canonical_row(run_id="r1"))
    k2 = _identity_of(_canonical_row(run_id="r2"))
    assert k1 == k2  # application identity ignores run_id
    assert k1.startswith("head:")
    assert "run" not in k1.replace("run-canonical", "")  # no run_id in identity
    assert k1 == ("head:7:effnet:mood:temporal_global:1.0:1.0:direct_l2:effnet_ptc:shared_effnet_ptc_boundary")
    assert "7" in k1 and "direct_l2" in k1 and "1.0" in k1
    # Different heads / configs / semantics are distinct identities.
    assert _identity_of(_canonical_row(head="timbre")) != k1
    assert _identity_of(_canonical_row(config_id=9)) != k1
    assert _identity_of(_canonical_row(semantics="std_scaled")) != k1
    assert _identity_of(_canonical_row(threshold_configured=1.1)) != k1


def test_head_phase_identity_not_an_analyze_strategy_key():
    assert _identity_of(_canonical_row()).split(":")[0] == "head"
    assert not _identity_of(_canonical_row()).startswith(("ptc:", "ctp:", "global_pool:"))


# ---------------------------------------------------------------------------
# P1-S3: build rows (canonical + archival) from manifests
# ---------------------------------------------------------------------------


def test_build_rows_from_canonical_manifest():
    rec = _canonical_config_record(head="mood", n_pooled=2)
    manifest = _canonical_manifest(run_id="r-canon", results=(rec,), reference_corpus_hash="h")
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash="h")
    assert len(rows) == 1
    r = rows[0]
    assert r.run_id == "r-canon"
    assert r.config_id == 7
    assert r.threshold is None
    assert r.threshold_configured == pytest.approx(1.0)
    assert r.threshold_effective == pytest.approx(1.0)
    assert r.semantics == "direct_l2"
    assert r.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    assert r.head_pool_variant == HEAD_POOL_VARIANT
    assert r.status == "done" and r.n_songs == 2 and r.n_pooled == 2
    assert is_canonical_row(r)


def test_build_archival_rows_from_legacy_manifest():
    """A legacy (head_pooling) manifest maps to archival run_id='legacy' rows."""
    rec = LegacyHeadPhaseConfigRecord(
        backbone="effnet",
        head="genre",
        bin_mode="temporal_global",
        threshold=1.0,
        status="done",
        reason="",
        n_songs=4,
        n_pooled=4,
        finite=True,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
    )
    legacy_manifest = LegacyHeadPhaseManifest(
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        backbones=("effnet",),
        heads=("genre",),
        bin_modes=("temporal_global",),
        thresholds=(1.0,),
        song_ids=("s1", "s2", "s3", "s4"),
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        results=(rec,),
        skip_reasons=(),
        done=1,
        skipped=0,
        errors=0,
        finite=True,
        primary_analysis_succeeded=True,
    )
    rows = build_archival_provenance_rows(legacy_manifest, reference_corpus_hash="h")
    assert len(rows) == 1
    r = rows[0]
    assert r.run_id == LEGACY_RUN_ID
    assert r.threshold == pytest.approx(1.0)
    assert r.config_id is None
    assert r.threshold_configured is None and r.threshold_effective is None and r.semantics is None
    assert r.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    assert r.head_pool_variant == HEAD_POOL_VARIANT
    assert is_canonical_row(r) is False


# ---------------------------------------------------------------------------
# P1-S3: query_head_phase_done / additive guarantees
# ---------------------------------------------------------------------------


def test_query_head_phase_done_returns_only_canonical_done_keys(con):
    recs = (
        _canonical_config_record(head="mood", status="done", n_pooled=2),
        _canonical_config_record(head="timbre", status="skipped", n_pooled=0, reason="no ready stream"),
    )
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_canonical_manifest(results=recs)))
    done = query_head_phase_done(con)
    assert done == {_identity_of(_canonical_row(head="mood"))}


def test_head_phase_provenance_additive_does_not_touch_analyze_metrics(con):
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_canonical_manifest()))
    assert db.query_analysis_done(con) == set()
    assert con.execute("SELECT * FROM analyze_metrics").fetchall() == []
    assert db.query_binned_classify_done(con) == set()
    assert con.execute("SELECT * FROM binned_classify_ctp").fetchall() == []


def test_head_phase_rows_never_primary_winner_candidate(con):
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_canonical_manifest()))
    assert db.query_analysis_done(con) == set()
    assert con.execute("SELECT strategy_key, strategy_type FROM analyze_metrics").fetchall() == []
    for r in load_head_phase_provenance(con):
        assert r.config_key.startswith("head:")
        assert r.config_key.split(":")[0] == "head"


def test_head_phase_song_ids_are_primary_corpus_subset():
    primary = MatchingCorpusManifest(song_ids=("s1", "s2", "s3", "s4"), corpus_hash="h", backbone="effnet")
    head_sids = ("s1", "s3")
    manifest = _canonical_manifest(song_ids=head_sids, results=(_canonical_config_record(n_songs=2, n_pooled=2),))
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash=primary.corpus_hash)
    assert set(head_sids) <= set(primary.song_ids)
    assert all(r.reference_corpus_hash == "h" for r in rows)
    assert all(r.n_songs == 2 for r in rows)


# ---------------------------------------------------------------------------
# P1-S3/S1-S4: LEGACY run.py glue appends archival-only rows
# ---------------------------------------------------------------------------


def _legacy_pooling_manifest(song_ids=("s1", "s2"), status="done", n_pooled=2):
    rec = LegacyHeadPhaseConfigRecord(
        backbone="effnet",
        head="mood",
        bin_mode="temporal_global",
        threshold=1.0,
        status=status,
        reason="",
        n_songs=len(song_ids),
        n_pooled=n_pooled,
        finite=True,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
    )
    return LegacyHeadPhaseManifest(
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        backbones=("effnet",),
        heads=("mood",),
        bin_modes=("temporal_global",),
        thresholds=(1.0,),
        song_ids=tuple(song_ids),
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        results=(rec,),
        skip_reasons=(),
        done=1 if status == "done" else 0,
        skipped=0 if status == "done" else 1,
        errors=0,
        finite=True,
        primary_analysis_succeeded=True,
    )


def test_head_phase_wiring_extracts_effnet_corpus_and_appends_archival(con, monkeypatch):
    """_head_phase derives the EffNet corpus, pools (legacy), appends ARCHIVAL rows only."""
    captured = {}
    manifest = _legacy_pooling_manifest()

    def _fake_pooling(_con, **kwargs):
        captured["kwargs"] = kwargs
        return manifest

    monkeypatch.setattr(classify_mod, "run_shared_ptc_head_pooling", _fake_pooling)

    cfg = {
        "matching_corpus": {
            "effnet": MatchingCorpusManifest(song_ids=("s1", "s2"), corpus_hash="h", backbone="effnet")
        },
        "backbones": ["effnet"],
        "heads": ["mood"],
        "force": True,
    }
    run_mod._head_phase(con, cfg)

    kwargs = captured["kwargs"]
    assert kwargs["song_ids"] == frozenset({"s1", "s2"})
    assert kwargs["backbones"] == ["effnet"]
    assert kwargs["heads"] == ["mood"]
    assert kwargs["force"] is True
    assert cfg["head_phase_manifest"] is manifest
    # Archival-only: a legacy row with threshold populated, config fields NULL.
    rows = load_head_phase_provenance_all(con)
    assert len(rows) == 1
    r = rows[0]
    assert r.run_id == LEGACY_RUN_ID
    assert r.threshold == pytest.approx(1.0)
    assert r.config_id is None and r.threshold_configured is None and r.semantics is None
    assert r.reference_corpus_hash == "h"
    # No canonical current row is ever produced by the legacy glue (D1).
    assert load_head_phase_provenance(con) == []


def test_head_phase_wiring_falls_back_to_first_manifest_and_warns_on_zero_done(con, monkeypatch, caplog):
    """No effnet manifest -> fall back to first manifest; no pooled output warns."""

    def _fake_pooling(_con, **kwargs):  # noqa: ARG001 - interface-parity stub
        return _legacy_pooling_manifest(song_ids=("s9",), status="skipped", n_pooled=0)

    monkeypatch.setattr(classify_mod, "run_shared_ptc_head_pooling", _fake_pooling)
    cfg = {
        "matching_corpus": {"musicnn": MatchingCorpusManifest(song_ids=("s9",), corpus_hash="hm", backbone="musicnn")}
    }
    with caplog.at_level(logging.WARNING, logger="scripts.embedding_research.run"):
        run_mod._head_phase(con, cfg)
    assert cfg["head_phase_manifest"] is not None
    assert "no pooled output" in caplog.text
    rows = load_head_phase_provenance_all(con)
    assert len(rows) == 1 and rows[0].run_id == LEGACY_RUN_ID
    assert load_head_phase_provenance(con) == []
