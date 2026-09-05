"""Plan D Phase 3 — catalog-first bounded retrieval analysis (P3-S1..P3-S4).

Proves the catalog-first PRIMARY analysis path implemented by
``scripts/embedding_research/common/catalog_analysis.py`` and the run-scoped write/reader contract
in ``scripts/embedding_research/db/analyze_scope.py``:

* end-to-end on a synthetic corpus: catalog build -> disposable corpus view -> bounded scoring with
  ``seg_meta.weight`` candidate weights -> finite run-scoped metrics rows (aggregate + per-song);
* the analysis result carries config/score-variant identity (config ids, score variant +
  SCORING_SEMANTICS_VERSION, keyset/content view hashes) and is finite-only;
* run-scoping: an analysis run only touches rows it owns — unrelated retained-run rows and
  baseline/corpus rows survive, and NO code path in the analysis callers performs a global
  ``DELETE FROM analyze_metrics``;
* the run-scoped reader contracts (load_analyze_metrics / query_analysis_done with ``run_id``)
  restrict to the run's recorded output scope;
* archival separation: the legacy flat/PTC/head/CTP copied-cache readers are labelled ARCHIVAL and
  are NOT importable/reachable from the catalog-first primary path;
* non-finite results are rejected (never persisted).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import bounded_scoring
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.db import analyze_scope, load_analyze_metrics, query_analysis_done
from scripts.embedding_research.db import provenance as prov


def _unit(rng, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}


def _build_store(con, tmp_path, factory, *, seed: int = 3, song_ids=_SONGS):
    """Publish one ready effnet stream per song and build a COMPACT snapshot harness.

    ``con`` is the RESEARCH connection; the returned harness's ``.con`` is the compact snapshot
    connection used for all catalog reads (P1-S6(c)).
    """
    from scripts.embedding_research import catalog

    out = tmp_path / "out"
    rng = np.random.default_rng(seed)
    streams = {}
    for song in song_ids:
        streams[(song, "effnet")] = _unit(rng, 10, 6)
    return factory(
        con,
        out,
        streams=streams,
        configs=[
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        song_ids=list(song_ids),
        run_id="run-cat-1",
    )


def _cfg(run_id: str, song_ids=_SONGS, artists=_ARTISTS) -> ca.CatalogAnalysisConfig:
    return ca.CatalogAnalysisConfig(run_id=run_id, backbone="effnet", song_ids=song_ids, artists=artists)


def _analyze(store, harness, con, cfg):
    """Run catalog-first analysis: catalog reads on the compact snapshot, research writes on con."""
    return ca.run_catalog_analysis(store, harness.con, cfg, research_con=con)


# --------------------------------------------------------------------------- #
# P3-S1/P3-S2 — catalog-first end-to-end, finite, identity-carrying result      #
# --------------------------------------------------------------------------- #


def test_catalog_analysis_end_to_end_finite_and_identity_carrying(con, tmp_path, compact_catalog_factory):
    harness = _build_store(con, tmp_path, compact_catalog_factory)
    try:
        store = harness.stream_store
        cfg = _cfg("run-an-1")
        result = ca.analyze_catalog_corpus(store, harness.con, cfg, research_con=con)

        assert result.finite is True
        assert result.run_id == "run-an-1"
        assert result.backbone == "effnet"
        assert len(result.view_content_hash) == 64
        assert result.score_variant == "max_per_candidate_segment"
        assert result.scoring_semantics_version == 1
        assert result.config_ids  # resolved to the single canonical compact seg_config
        # P1-S4 transient representation-class metadata: every participating config is reported by
        # its class, each class canonical == the (single) config for an un-collapsed fixture.
        assert tuple(sorted(result.config_ids)) == result.config_ids
        assert result.representation_classes
        assert {c for cid in result.representation_classes for c in cid.config_ids} == set(result.config_ids)
        for cls in result.representation_classes:
            assert cls.canonical_config_id in result.config_ids
            assert all(a in result.config_ids for a in cls.alias_ids)
        # A single distinct config forms one singleton class (canonical == itself, no aliases).
        assert all(cls.n_configs == 1 and cls.alias_ids == () for cls in result.representation_classes)
        assert result.n_queries == len(_SONGS)
        for key in ("map_k", "mrr", "ndcg_k", "recall_k", "disc_artist"):
            assert np.isfinite(result.metrics[key]), key
        assert all(pq.all_finite() for pq in result.per_query)
        # Candidate weight factor is non-uniform (weighted corpus) => scores finite and ordered.
        assert result.strategy_key.startswith("catalog:effnet:max_per_candidate_segment:v1:")
        # Determinism: identical inputs -> identical metrics.
        again = _analyze(store, harness, con, _cfg("run-an-2"))
        for key in result.metrics:
            np.testing.assert_allclose(again.metrics[key], result.metrics[key], rtol=1e-6)
    finally:
        harness.close()


def test_catalog_analysis_write_is_run_scoped_and_readable(con, tmp_path, compact_catalog_factory):
    harness = _build_store(con, tmp_path, compact_catalog_factory)
    try:
        store = harness.stream_store
        result = _analyze(store, harness, con, _cfg("run-an-1"))
        sk = analyze_scope.write_catalog_analyze_rows(con, run_id="run-an-1", result=result)

        assert sk == result.strategy_key
        agg = con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (sk,)).fetchone()[0]
        assert agg > 0
        per_song = con.execute("SELECT COUNT(*) FROM song_retrieval_metrics WHERE strategy_key=?", (sk,)).fetchone()[0]
        assert per_song == len(_SONGS)
        # Run-scoped reader contracts restrict to this run's recorded scope.
        df = load_analyze_metrics(con, run_id="run-an-1")
        assert not df.empty
        assert set(df["strategy_key"]) == {sk}
        assert query_analysis_done(con, run_id="run-an-1") == {(sk, "cosine", result.k)}
        # Scope recorded in run_provenance for the later reset migration.
        rows = prov.read_run_provenance(con, run_id="run-an-1")
        blob = next(r["output_artifact_hashes"] for r in rows if r["phase"] == "analyze")
        assert sk in blob
        assert analyze_scope.parse_analyze_scope(blob.splitlines()[0]) is not None
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# P3-S4 — no global delete; unrelated retained rows preserved                  #
# --------------------------------------------------------------------------- #


def _seed_retained_and_unrelated_rows(con):
    # A retained, unrelated retained run's analyze rows + provenance row.
    prov.write_run_provenance(
        con,
        run_id="retained-run-0",
        phase="analyze",
        status="complete",
        started_at=1,
        finished_at=2,
        retained=True,
        output_artifact_hashes="other:scope",
    )
    unrelated = "global_pool:effnet:mean"
    con.execute(
        "INSERT INTO analyze_metrics (strategy_key, strategy_type, sim_metric, k, metric, value) "
        "VALUES (?, 'global_pool', 'cosine', 10, 'disc_general', 0.99)",
        (unrelated,),
    )
    con.execute(
        "INSERT INTO song_retrieval_metrics (strategy_key, sim_metric, k, song_id, ap_k) "
        "VALUES (?, 'cosine', 10, 's1', 0.5)",
        (unrelated,),
    )
    return unrelated


def test_no_global_analyze_metrics_delete_in_analysis_callers():
    """No analysis caller performs a global DELETE FROM analyze_metrics."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    # The destructive CALL (`execute("DELETE FROM analyze_metrics")`) must be absent.  Prose in
    # docstrings/comments that says it is removed is allowed.
    offenders = []
    for name in (
        "common/catalog_analysis.py",
        "db/analyze_scope.py",
        "run.py",
    ):
        src = (root / name).read_text()
        if 'execute("DELETE FROM analyze_metrics"' in src:
            offenders.append(name)
    assert offenders == [], f"global analyze_metrics delete call still present in {offenders}"


def test_catalog_analysis_preserves_retained_and_unrelated_rows(con, tmp_path, compact_catalog_factory):
    unrelated = _seed_retained_and_unrelated_rows(con)
    harness = _build_store(con, tmp_path, compact_catalog_factory)
    try:
        store = harness.stream_store
        # First run writes its own scope.
        res1 = _analyze(store, harness, con, _cfg("run-an-1"))
        sk1 = analyze_scope.write_catalog_analyze_rows(con, run_id="run-an-1", result=res1)
        # Second run (different corpus run) writes its own scope — must not disturb run 1 or retained rows.
        res2 = _analyze(store, harness, con, _cfg("run-an-2"))
        sk2 = analyze_scope.write_catalog_analyze_rows(con, run_id="run-an-2", result=res2)

        # Unrelated retained rows untouched.
        assert con.execute(
            "SELECT value FROM analyze_metrics WHERE strategy_key=? AND metric='disc_general'",
            (unrelated,),
        ).fetchone()[0] == pytest.approx(0.99)
        assert (
            con.execute("SELECT COUNT(*) FROM song_retrieval_metrics WHERE strategy_key=?", (unrelated,)).fetchone()[0]
            == 1
        )
        # Each run's own rows still present.
        assert con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (sk1,)).fetchone()[0] > 0
        assert con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (sk2,)).fetchone()[0] > 0
        # Retained provenance row intact.
        rows = prov.read_run_provenance(con, run_id="retained-run-0")
        assert len(rows) == 1 and rows[0]["retained"] is True
    finally:
        harness.close()


def test_catalog_analysis_path_never_imports_archival_cache_readers():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(ca.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_roots = ("cache.flat_vecs", "cache.binned_ptc", "cache.binned_ptc_heads", "cache.binned_ctp")
    leaked = [i for i in imported if i.startswith(forbidden_roots)]
    assert leaked == [], f"catalog-first path must not import archival readers: {leaked}"


# --------------------------------------------------------------------------- #
# P3-S2 — non-finite rejection (never persisted)                                #
# --------------------------------------------------------------------------- #


def test_non_finite_bounded_score_is_rejected(con, tmp_path, compact_catalog_factory, monkeypatch):
    harness = _build_store(con, tmp_path, compact_catalog_factory)
    try:
        store = harness.stream_store

        import types

        def _bad_result(*_args, **_kwargs):
            return types.SimpleNamespace(
                finite=False,
                score=float("nan"),
                numerator=float("nan"),
                denominator=float("nan"),
                winner_counts={},
                retained_count=0,
                dropped_count=0,
            )

        monkeypatch.setattr(bounded_scoring, "score_bounded_exact", _bad_result)
        with pytest.raises(ca.NonFiniteResultError):
            _analyze(store, harness, con, _cfg("run-an-bad"))
        # Nothing persisted under any strategy scope.
        assert analyze_scope.run_row_scopes(con, run_id="run-an-bad") == frozenset()
    finally:
        harness.close()
