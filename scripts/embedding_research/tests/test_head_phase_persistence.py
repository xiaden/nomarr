"""Spec-first tests for Plan B, Phase 2: head-phase provenance persistence.

Covers the additive persistence DTO (P2-S1), the explicit per-configuration
identity and its disjointness from CTP/head-specific-segmentation keys (P2-S3),
and the corpus/non-comparison/no-CTP/no-winner guarantees (P2-S4):

* named-column writes and finite-value validation (P2-S1);
* primary ``analyze_metrics`` rows and corpus hashes stay UNCHANGED (P2-S1);
* each ``(effnet, head, bin_mode, threshold, boundary_source, head_pool_variant)``
  tuple has an explicit ``head:`` identity disjoint from ``ptc:``/``ctp:``/``global_pool:``
  keys (P2-S3);
* a CTP strategy key and any head-specific-segmentation threshold cannot masquerade
  as a shared-boundary row (P2-S3);
* head-phase rows/cache entries carry the same primary EffNet corpus or a clearly
  declared derived head-availability subset; unequal sets are never compared
  silently; head-phase rows never appear as CTP or as a primary winner candidate
  (P2-S4).
"""

from __future__ import annotations

import logging

import duckdb
import pytest

import scripts.embedding_research.classify as classify_mod
from scripts.embedding_research import db
from scripts.embedding_research import run as run_mod
from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.corpus import MatchingCorpusManifest, validate_matching_corpus
from scripts.embedding_research.db import head_phase as head_phase_db
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.head_phase import (
    HeadPhaseProvenanceRow,
    build_head_phase_provenance_rows,
    head_phase_config_key,
    load_head_phase_provenance,
    query_head_phase_done,
    write_head_phase_provenance,
)
from scripts.embedding_research.head_pooling import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HEAD_POOL_VARIANT,
    HeadPhaseConfigRecord,
    HeadPhaseManifest,
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


def _manifest(
    *,
    song_ids=("s1", "s2"),
    results=None,
    backbones=("effnet",),
    heads=("mood",),
    bin_modes=("temporal_global",),
    thresholds=(1.0,),
    skip_reasons=(),
    done=None,
    skipped=None,
    errors=None,
):
    results = results or (
        HeadPhaseConfigRecord(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=1.0,
            status="done",
            reason="",
            n_songs=len(song_ids),
            n_pooled=len(song_ids),
            finite=True,
            boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        ),
    )
    return HeadPhaseManifest(
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        backbones=backbones,
        heads=heads,
        bin_modes=bin_modes,
        thresholds=thresholds,
        song_ids=tuple(song_ids),
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        results=tuple(results),
        skip_reasons=tuple(skip_reasons),
        done=len(results) if done is None else done,
        skipped=0 if skipped is None else skipped,
        errors=0 if errors is None else errors,
        finite=all(r.finite for r in results),
        primary_analysis_succeeded=True,
    )


# ---------------------------------------------------------------------------
# P2-S1: named-column writes + finite validation + additive persistence
# ---------------------------------------------------------------------------


def test_write_head_phase_provenance_uses_named_columns(con):
    """DTO/DDL column order can differ; writes must use named columns (P2-S1)."""
    captured = {}

    class _Recorder:
        def executemany(self, sql, params):
            captured["sql"] = sql
            return con.executemany(sql, params)

    row = HeadPhaseProvenanceRow(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=1.0)
    write_head_phase_provenance(_Recorder(), [row])

    assert "INSERT INTO head_phase_provenance" in captured["sql"]
    assert (
        "(backbone, head, bin_mode, threshold, boundary_source, head_pool_variant, "
        "status, reason, n_songs, n_pooled, finite, scoring_semantics_version, "
        "reference_corpus_hash)"
    ) in captured["sql"]
    assert captured["sql"].count("?") == 13


def test_write_head_phase_provenance_roundtrip(con):
    row = HeadPhaseProvenanceRow(
        backbone="effnet",
        head="mood",
        bin_mode="temporal_global",
        threshold=1.0,
        status="done",
        reason="",
        n_songs=2,
        n_pooled=2,
        finite=True,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        reference_corpus_hash="hash-primary",
    )
    write_head_phase_provenance(con, [row])

    loaded = load_head_phase_provenance(con)
    assert len(loaded) == 1
    got = loaded[0]
    assert got == row
    assert got.config_key == head_phase_config_key(
        backbone="effnet", head="mood", bin_mode="temporal_global", threshold=1.0
    )
    assert got.config_key.startswith("head:effnet:mood:temporal_global:1.000:")


def test_build_rows_from_manifest():
    manifest = _manifest()
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash="hash-primary")
    assert len(rows) == 1
    r = rows[0]
    assert r.backbone == "effnet"
    assert r.head == "mood"
    assert r.bin_mode == "temporal_global"
    assert r.threshold == pytest.approx(1.0)
    assert r.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    assert r.head_pool_variant == HEAD_POOL_VARIANT
    assert r.status == "done"
    assert r.n_songs == 2 and r.n_pooled == 2
    assert r.finite is True
    assert r.scoring_semantics_version == SCORING_SEMANTICS_VERSION
    assert r.reference_corpus_hash == "hash-primary"


def test_build_rows_from_manifest_one_row_per_config():
    recs = (
        HeadPhaseConfigRecord(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=1.0,
            status="done",
            reason="",
            n_songs=2,
            n_pooled=2,
            finite=True,
            boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        ),
        HeadPhaseConfigRecord(
            backbone="effnet",
            head="timbre",
            bin_mode="temporal_global",
            threshold=1.0,
            status="skipped",
            reason="no cached head session",
            n_songs=0,
            n_pooled=0,
            finite=True,
            boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        ),
    )
    manifest = _manifest(results=recs, heads=("mood", "timbre"))
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash="h")
    assert len(rows) == 2
    assert {r.head for r in rows} == {"mood", "timbre"}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threshold": float("nan")},
        {"threshold": float("inf")},
        {"n_songs": -1},
        {"n_pooled": -1},
        {"n_pooled": 5, "n_songs": 3},  # pooled cannot exceed attempted
    ],
)
def test_head_phase_row_finite_validation(kwargs):
    """Non-finite/invalid numeric values are rejected — never persisted (P2-S1)."""
    base = {"backbone": "effnet", "head": "mood", "bin_mode": "temporal_global", "threshold": 1.0}
    base.update(kwargs)
    with pytest.raises(ValueError):
        HeadPhaseProvenanceRow(**base)


def test_head_phase_row_rejects_non_effnet_boundary_source():
    """A row whose boundary_source is not effnet_ptc (e.g. a CTP path) is rejected (P2-S3)."""
    with pytest.raises(ValueError, match="boundary_source"):
        HeadPhaseProvenanceRow(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=1.0,
            boundary_source="ctp",
        )


def test_head_phase_row_rejects_wrong_pool_variant():
    """A hypothetical head-specific-segmentation variant cannot be a shared-boundary row (P2-S3)."""
    with pytest.raises(ValueError, match="head_pool_variant"):
        HeadPhaseProvenanceRow(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=1.0,
            head_pool_variant="head_specific_segmentation",
        )


def test_head_phase_provenance_additive_does_not_touch_analyze_metrics(con):
    """Writing head-phase provenance is additive: analyze_metrics stays empty (P2-S1)."""
    manifest = _manifest()
    rows = build_head_phase_provenance_rows(manifest, reference_corpus_hash="h")
    write_head_phase_provenance(con, rows)

    assert len(db.query_analysis_done(con)) == 0  # no primary analyze rows created
    metrics = con.execute("SELECT * FROM analyze_metrics").fetchall()
    assert metrics == []
    # The provenance rows themselves are present and carry the reference corpus.
    loaded = load_head_phase_provenance(con)
    assert len(loaded) == 1
    assert loaded[0].reference_corpus_hash == "h"


def test_query_head_phase_done_returns_only_done_keys(con):
    recs = (
        HeadPhaseConfigRecord(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=1.0,
            status="done",
            reason="",
            n_songs=2,
            n_pooled=2,
            finite=True,
            boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        ),
        HeadPhaseConfigRecord(
            backbone="effnet",
            head="timbre",
            bin_mode="temporal_global",
            threshold=1.0,
            status="skipped",
            reason="no cached head session",
            n_songs=0,
            n_pooled=0,
            finite=True,
            boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        ),
    )
    write_head_phase_provenance(con, build_head_phase_provenance_rows(_manifest(results=recs), "h"))
    done = query_head_phase_done(con)
    assert done == {head_phase_config_key(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=1.0)}


# ---------------------------------------------------------------------------
# P2-S3: explicit configuration identity, disjoint from CTP / head-specific keys
# ---------------------------------------------------------------------------


def test_head_phase_config_key_disjoint_namespace():
    """The head-phase identity lives in a ``head:`` namespace, disjoint from primary/CTP keys."""
    head_key = head_phase_config_key(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=0.5)
    assert head_key.startswith("head:")
    assert "effnet_ptc" in head_key
    assert HEAD_POOL_VARIANT in head_key
    for prefix in ("global_pool:", "ptc:", "ctp:"):
        assert not head_key.startswith(prefix), f"head-phase key must not use {prefix!r} namespace"


def test_ctp_and_ptc_strategy_keys_cannot_masquerade_as_head_phase_row():
    """A CTP (or PTC) strategy key is not a shared-boundary row identity (P2-S3)."""
    shared = {"std_thresh": 0.5, "rep_a": "mean", "rep_b": "max", "agg_method": "target_weighted"}
    ctp_key = run_mod._ctp_strategy_key("effnet", "ctp_mood_0.5", {"head": "mood", **shared})
    ptc_key = run_mod._ptc_strategy_key("effnet", "ptc_temporal_global_0.5", {"bin_mode": "temporal_global", **shared})

    head_key = head_phase_config_key(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=0.5)

    assert ctp_key.startswith("ctp:") and ptc_key.startswith("ptc:")
    assert head_key != ctp_key and head_key != ptc_key
    assert "boundary_source" not in ctp_key and HEAD_POOL_VARIANT not in ctp_key
    # Persisting a CTP-style identity as a head-phase row is rejected (boundary_source).
    with pytest.raises(ValueError, match="boundary_source"):
        HeadPhaseProvenanceRow(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=0.5,
            boundary_source="ctp",
        )


def test_head_specific_segmentation_threshold_cannot_masquerade():
    """A head-specific-segmentation threshold uses a different variant → not a shared-boundary row (P2-S3)."""
    # Same (backbone, head, bin_mode, threshold) but a head-specific segmentation
    # variant must carry a distinct head_pool_variant (forbidden by the DTO).
    shared_key = head_phase_config_key(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=0.7)
    hypothetical_key = head_phase_config_key(
        backbone="effnet",
        head="mood",
        bin_mode="temporal_global",
        threshold=0.7,
        head_pool_variant="head_specific_segmentation",
    )
    assert shared_key != hypothetical_key
    with pytest.raises(ValueError, match="head_pool_variant"):
        HeadPhaseProvenanceRow(
            backbone="effnet",
            head="mood",
            bin_mode="temporal_global",
            threshold=0.7,
            head_pool_variant="head_specific_segmentation",
        )


def test_head_phase_identity_not_an_analyze_strategy_key():
    """The head-phase identity can never enter the primary analyze_metrics key space (P2-S3)."""
    head_key = head_phase_config_key(backbone="effnet", head="mood", bin_mode="temporal_global", threshold=0.5)
    # Primary analyze strategy keys are prefixed global_pool:/ptc:/ctp: and carry no
    # boundary_source/head_pool_variant — disjoint by construction.
    assert head_key.split(":")[0] == "head"


# ---------------------------------------------------------------------------
# P2-S4: same-primary-corpus / declared subset / no-CPT / no-winner
# ---------------------------------------------------------------------------


def test_head_phase_song_ids_are_primary_corpus_subset():
    """Head-phase rows declare the primary EffNet corpus and the derived subset (P2-S4)."""
    primary = MatchingCorpusManifest(song_ids=("s1", "s2", "s3", "s4"), corpus_hash="hash-primary", backbone="effnet")
    # Head availability is only present for a subset of the primary corpus.
    head_manifest = _manifest(song_ids=("s1", "s3"))
    rows = build_head_phase_provenance_rows(head_manifest, reference_corpus_hash=primary.corpus_hash)

    head_sids = set(head_manifest.song_ids)
    assert head_sids <= set(primary.song_ids)
    assert head_sids < set(primary.song_ids)  # genuinely a subset here
    assert all(r.reference_corpus_hash == primary.corpus_hash for r in rows)
    # The head phase did not silently claim the full primary corpus.
    assert all(r.n_songs == len(head_sids) for r in rows)


def test_unequal_sets_never_compared_silently():
    """Any primary/head set mismatch is rejected loudly — never silently intersected (P2-S4)."""
    primary = MatchingCorpusManifest(song_ids=("s1", "s2", "s3"), corpus_hash="hash-primary", backbone="effnet")
    # A head phase that observed MORE songs than the primary corpus is a mismatch
    # against the declared reference; the corpus validator must reject it.
    with pytest.raises(ValueError, match="song-ID set mismatch"):
        validate_matching_corpus(primary, ["s1", "s2", "s3", "s4"], "head-phase")


def test_head_phase_rows_never_appear_as_ctp(con):
    """Head-phase rows live only in head_phase_provenance with effnet_ptc source (P2-S4)."""
    manifest = _manifest()
    write_head_phase_provenance(con, build_head_phase_provenance_rows(manifest, "h"))

    rows = load_head_phase_provenance(con)
    assert all(r.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC for r in rows)
    # They never appear in any CTP storage table.
    assert db.query_binned_classify_done(con) == set()
    ctp_rows = con.execute("SELECT * FROM binned_classify_ctp").fetchall()
    assert ctp_rows == []


def test_head_phase_rows_never_primary_winner_candidate(con):
    """Head-phase rows never enter analyze_metrics, so never a primary winner candidate (P2-S4)."""
    manifest = _manifest()
    write_head_phase_provenance(con, build_head_phase_provenance_rows(manifest, "h"))

    # Primary winner candidates are drawn from analyze_metrics rows (strategy keys).
    assert db.query_analysis_done(con) == set()
    metrics = con.execute("SELECT strategy_key, strategy_type FROM analyze_metrics").fetchall()
    assert metrics == []
    # And the head-phase identity is structurally outside the winner-key namespaces.
    for r in load_head_phase_provenance(con):
        assert r.config_key.startswith("head:")


# ---------------------------------------------------------------------------
# P2-S5: _head_phase pipeline glue (run.py wiring)
# ---------------------------------------------------------------------------


def test_head_phase_wiring_extracts_effnet_corpus_and_persists(con, monkeypatch):
    """_head_phase derives the EffNet corpus, calls pooling, persists provenance, sets cfg."""
    captured = {}
    written: list[tuple] = []

    def _fake_pooling(_con, **kwargs):
        captured["kwargs"] = kwargs
        return _manifest()

    def _fake_build(_m, reference_corpus_hash=None):
        captured["corpus_hash"] = reference_corpus_hash
        return ["row-with-hash"]

    def _fake_write(conn, rows):
        written.append((conn, rows))

    monkeypatch.setattr(classify_mod, "run_shared_ptc_head_pooling", _fake_pooling)
    monkeypatch.setattr(head_phase_db, "build_head_phase_provenance_rows", _fake_build)
    monkeypatch.setattr(head_phase_db, "write_head_phase_provenance", _fake_write)

    cfg = {
        "matching_corpus": {
            "effnet": MatchingCorpusManifest(song_ids=("s1", "s2"), corpus_hash="hash-primary", backbone="effnet")
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
    assert captured["corpus_hash"] == "hash-primary"
    assert cfg["head_phase_manifest"] is not None
    assert written and written[0][0] is con and written[0][1] == ["row-with-hash"]


def test_head_phase_wiring_falls_back_to_first_manifest_and_warns_on_zero_done(con, monkeypatch, caplog):
    """No effnet manifest -> fall back to first manifest; no pooled output warns.

    The "outputs unavailable" warning fires only when there is genuinely no pooled
    output (sum(n_pooled) == 0), not merely when done==0 (a fully-cached rerun has
    done==0 but n_pooled==n_songs>0 and must NOT warn).
    """
    captured = {}

    def _fake_pooling(_con, **kwargs):
        captured["kwargs"] = kwargs
        return _manifest(
            done=0,
            skipped=2,
            results=(
                HeadPhaseConfigRecord(
                    backbone="effnet",
                    head="mood",
                    bin_mode="temporal_global",
                    threshold=1.0,
                    status="skipped",
                    reason="no cached head session",
                    n_songs=2,
                    n_pooled=0,
                    finite=True,
                    boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
                ),
            ),
        )

    def _fake_build(_m, reference_corpus_hash=None):
        captured["corpus_hash"] = reference_corpus_hash
        return []

    monkeypatch.setattr(classify_mod, "run_shared_ptc_head_pooling", _fake_pooling)
    monkeypatch.setattr(head_phase_db, "build_head_phase_provenance_rows", _fake_build)
    monkeypatch.setattr(head_phase_db, "write_head_phase_provenance", lambda _conn, _rows: None)

    cfg = {
        "matching_corpus": {
            "musicnn": MatchingCorpusManifest(song_ids=("s9",), corpus_hash="hash-musicnn", backbone="musicnn")
        }
    }
    with caplog.at_level(logging.WARNING, logger="scripts.embedding_research.run"):
        run_mod._head_phase(con, cfg)

    assert captured["kwargs"]["song_ids"] == frozenset({"s9"})
    assert captured["corpus_hash"] == "hash-musicnn"
    assert cfg["head_phase_manifest"] is not None
    assert "no pooled output" in caplog.text
