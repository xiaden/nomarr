"""Plan D Phase 4 (P4-S3) — synthetic scale coverage end-to-end (catalog-first analysis).

This module runs the FULL catalog-first analysis path over a sized **synthetic** corpus —
the threshold/corpus surface Phase 4 must exercise:

* multiple songs;
* **several segments per song** (each song is a deterministic concatenation of distinct
  unit-norm block clusters, so the running-centroid segmentation reliably yields several
  membership segments — verified below, never assumed);
* one or more canonical configs (two distinct canonical ``SegConfigInput`` configs are
  built, exercising the multi-config candidate surface);
* a **documented patch distribution and dimension**: each song is ``per_block`` patches of
  each of ``n_blocks`` distinct unit centers, dimension ``D`` (float32, L2-unit rows).

And it drives the analysis end-to-end (catalog -> materialize the disposable corpus view ->
bounded scoring -> run-scoped metrics) asserting:

* the result is finite everywhere (result + every per-query + metrics);
* correct shape / count semantics: one per-query result per query song, every query scored
  against every OTHER candidate song (leave-one-out), and each per-query's candidate-keys
  equal the exact set of other-song medoid row addresses from the catalog (checked against
  ``segments_by_config_song``), so the row/count semantics are pinned to the catalog;
* determinism: an identical second run reproduces the metrics within the documented rtol;
* a labelled FIXTURES-ONLY benchmark report (``fixture_benchmark.run_bounded_benchmark``)
  with the full P4-S3 metadata set validates clean and is labelled fixtures-only — every
  number here is a fixture, never an empirical corpus/model claim.
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research import fixture_benchmark
from scripts.embedding_research.common import catalog_analysis as ca
from scripts.embedding_research.db import analyze_scope, load_analyze_metrics
from scripts.embedding_research.streams.store import StreamStore

# --------------------------------------------------------------------------- #
# Documented synthetic-corpus surface (P4-S3).                                  #
# --------------------------------------------------------------------------- #
# Every value below is a documented FIXTURE parameter: there is no real corpus or model
# behind these numbers — they describe the deterministic synthetic matrix only.
_SONGS = ("s1", "s2", "s3", "s4", "s5", "s6")
_ARTISTS = {
    "s1": "A",
    "s2": "A",
    "s3": "A",
    "s4": "B",
    "s5": "B",
    "s6": "B",
}
#: Each song is N_BLOCKS distinct L2-unit block centers x PER_BLOCK patches each (uniform).
_BLOCKS = 4
_PER_BLOCK = 8
_DIM = 8
#: The two canonical segmentation configs (distinct thresholds => distinct config_ids).
_CONFIG_SPECS = (0.7, 0.5)


def _block_song(rng, blocks: int, per_block: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit row stream = ``blocks`` clusters of ``per_block`` each.

    Each block is ``per_block`` exact copies of one distinct random L2-unit center, so the
    running-centroid segmentation reliably emits one membership segment per block (the
    boundary distance between distinct centers is ~sqrt(2) >> any realistic threshold while
    intra-block distance is ~0).  This is a documented synthetic patch distribution: uniform
    across ``blocks`` centers, dimension ``d``, float32 unit rows.
    """
    rows: list[np.ndarray] = []
    for _ in range(blocks):
        center = rng.standard_normal(d)
        norm = float(np.linalg.norm(center))
        center = center / norm if norm > 1e-9 else center
        rows.extend([center] * per_block)
    return np.asarray(rows, dtype=np.float32)


def _build_scale_corpus(con, tmp_path, store_name: str):
    """Publish one multi-segment effnet stream per song and build TWO canonical configs."""
    from scripts.embedding_research import catalog

    store = StreamStore(con, output_root=str(tmp_path / store_name))
    rng = np.random.default_rng(1)
    for song in _SONGS:
        patches = _block_song(rng, _BLOCKS, _PER_BLOCK, _DIM)
        store.publish(song, "effnet", patches, run_id="run-embed")
    store.reconcile()

    configs = [
        catalog.SegConfigInput(
            backbone="effnet",
            bin_mode="temporal_global",
            threshold_configured=t,
            threshold_effective=t,
        )
        for t in _CONFIG_SPECS
    ]
    for i, config in enumerate(configs):
        rep = catalog.build_segmentation_catalog(con, store, [config], list(_SONGS), f"run-cat-{i + 1}", verify=True)
        assert rep.verify_ok is True
    return store


def _cfg(run_id: str) -> ca.CatalogAnalysisConfig:
    return ca.CatalogAnalysisConfig(run_id=run_id, backbone="effnet", song_ids=_SONGS, artists=_ARTISTS, k=5)


def test_scale_corpus_yields_several_segments_per_song(con, tmp_path):
    """The synthetic corpus genuinely exercises several segments per song (never assumed)."""
    from scripts.embedding_research import catalog

    _build_scale_corpus(con, tmp_path, "out")
    config_ids = [c.config_id for c in catalog.configs_by_backbone(con, "effnet")]
    assert len(config_ids) == len(_CONFIG_SPECS)  # both canonical configs built
    # A strict segment under the first (coarse) config is expected per block; assert the
    # threshold/corpus surface has several segments per song, not just one.
    for song in _SONGS:
        segs = catalog.segments_by_config_song(con, config_ids[0], song)
        assert len(segs) >= 2, f"song {song} produced too few segments: {len(segs)}"


def test_scale_catalog_analysis_end_to_end_finite_shape_and_counts(con, tmp_path):
    """Full catalog-first analysis is finite with correct per-query shape/count semantics."""
    store = _build_scale_corpus(con, tmp_path, "out")
    result = ca.analyze_catalog_corpus(store, con, _cfg("run-scale-1"))

    assert result.finite is True
    assert len(result.search_view_hash) == 64
    assert len(result.config_ids) == len(_CONFIG_SPECS)
    assert result.strategy_key.startswith("catalog:effnet:max_per_candidate_segment:v1:")

    # Run-scoped metrics are finite.
    for key in ("map_k", "mrr", "ndcg_k", "recall_k", "disc_artist"):
        assert np.isfinite(result.metrics[key]), key

    # Shape/count: one per-query result per query song; every query against every OTHER song.
    assert result.n_queries == len(_SONGS)
    assert len(result.per_query) == len(_SONGS)
    for pq in result.per_query:
        assert pq.all_finite() is True
        assert pq.query_song_id in _SONGS
        assert set(pq.candidate_scores) == set(_SONGS) - {pq.query_song_id}
        assert len(pq.candidate_scores) == len(_SONGS) - 1  # leave-one-out
        assert pq.dropped_count == 0  # primary retain_all_candidate_segments never drops
        assert pq.retained_count > 0
        assert pq.winner_counts  # winning query-source rows got credit
        assert all(np.isfinite(v) for v in pq.winner_counts.values())

    # The candidate-key provenance must equal the catalog's other-song medoid row addresses.
    _assert_candidate_keys_match_catalog(con, result)


def _assert_candidate_keys_match_catalog(con, result):
    """per-query candidate_keys equal the exact other-song medoid rows from the catalog."""
    from scripts.embedding_research import catalog

    config_ids = tuple(sorted(result.config_ids))
    by_song: dict[str, list[tuple[int, str, int, int]]] = {s: [] for s in _SONGS}
    for config_id in config_ids:
        for song in _SONGS:
            for meta in catalog.segments_by_config_song(con, int(config_id), song):
                by_song[song].append((int(config_id), song, int(meta.seg_id), int(meta.medoid_source_patch_idx)))
    for pq in result.per_query:
        expected = sorted(addr for song in _SONGS for addr in by_song[song] if song != pq.query_song_id)
        assert sorted(pq.candidate_keys) == expected, pq.query_song_id


def test_scale_analysis_deterministic_and_run_scoped_persisted(con, tmp_path):
    """Identical re-run reproduces metrics (rtol), and rows persist run-scoped + finite."""
    store = _build_scale_corpus(con, tmp_path, "out")
    res1 = ca.run_catalog_analysis(store, con, _cfg("run-scale-a"))
    res2 = ca.run_catalog_analysis(store, con, _cfg("run-scale-b"))
    for key in res1.metrics:
        np.testing.assert_allclose(res2.metrics[key], res1.metrics[key], rtol=1e-6)

    # Persist run-scope and read back finite aggregate + per-song rows.
    analyze_scope.write_catalog_analyze_rows(con, run_id="run-scale-a", result=res1)
    df = load_analyze_metrics(con, run_id="run-scale-a")
    assert not df.empty
    assert set(df["strategy_key"]) == {res1.strategy_key}
    agg = con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE strategy_key=?", (res1.strategy_key,)).fetchone()[0]
    assert agg > 0
    per_song = con.execute(
        "SELECT COUNT(*) FROM song_retrieval_metrics WHERE strategy_key=?", (res1.strategy_key,)
    ).fetchone()[0]
    assert per_song == len(_SONGS)
    assert analyze_scope.run_row_scopes(con, run_id="run-scale-a") == {(res1.strategy_key, "cosine", res1.k)}


def test_scale_analysis_attaches_validated_fixtures_only_benchmark_report():
    """A labelled fixtures-only benchmark report for this surface validates clean (P4-S3 metadata)."""
    rec = fixture_benchmark.run_bounded_benchmark(
        n_songs=len(_SONGS),
        segments_per_song=_BLOCKS,  # segments-per-song (per coarse config) documents the surface
        dimension=_DIM,
        backbone="effnet",
        query_chunk_size=64,
        candidate_chunk_size=64,
        working_memory_bytes=32 * 1024 * 1024,
        seed=1,
    )
    # The full P4-S3 metadata set is present and the record is labelled fixtures-only.
    assert rec.validate() == []
    assert rec.fixtures_only is True
    assert rec.n_songs == len(_SONGS)
    assert rec.dimension == _DIM
    assert rec.backbone == "effnet"
    assert rec.peak_tracemalloc_bytes > 0
    assert rec.elapsed_ms >= 0.0
