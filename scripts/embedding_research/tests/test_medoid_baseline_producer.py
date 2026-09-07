"""Analyze-side observed global-medoid baseline PRODUCER (spec-first).

These fixtures pin the reopened P1-S6 deliverable as made MANDATORY by execution-reporting
Plan A P2: the ANALYZE phase emits EXACTLY ONE observed ``global_pool:{backbone}:medoid``
baseline metric identity per successfully analyzed backbone, unconditionally (there is NO
``emit_medoid_baseline`` config key or argparse flag), scored as an ADDITIONAL retrieval pass
over the SAME corpus / sim_metric / k / metric scope as the segmented catalog classes,
persisted run-scoped under a NON-``catalog`` ``strategy_type``.  Zero-searchable songs are
excluded from both the baseline population and candidate search, per-class execution counts
are untouched (the P1-S3/S4 fixtures keep passing), and ``baseline.build_baseline_delta_rows``
over the persisted decoded rows yields the finite per-cell deltas the winners loader consumes.

Gates:

1. ``common.catalog_analysis.analyze_medoid_baseline`` returns metric keys IDENTICAL to a
   segmented class's (``map_k``/``mrr``/``ndcg_k``/``recall_k``/``disc_artist``)
   for the same backbone/corpus/k — cell alignment for the exact-scope baseline join;
2. a fully-silent (zero-searchable) song in ``song_ids`` is EXCLUDED from the medoid corpus
   (its presence never changes the baseline values);
3. driving the REAL ``run.py::_run_analyze`` (MANDATORY baseline — no ``emit_medoid_baseline``
   gate, no hidden switch) persists EXACTLY ONE ``global_pool`` row per backbone whose
   ``strategy_key == medoid_strategy_key_for(backbone)``, run-scoped, never a catalog row;
4. ``build_baseline_delta_rows`` over the persisted class + medoid rows yields a finite delta
   per segmented result sharing the exact scope.

No synthetic/coordinate-wise medoid, no durable cache, no cross-backbone union.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.embedding_research import catalog as catalog_mod
from scripts.embedding_research.baseline import (
    MEDOID_STRATEGY_TYPE,
    build_baseline_delta_rows,
    medoid_strategy_key_for,
    observed_global_medoid_unit_vector,
)
from scripts.embedding_research.common import catalog_analysis as ca

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_SONGS = ("s1", "s2", "s3", "s4")
_ARTISTS = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
_RUN = "run-p1s6-medoid-producer"
_CLASS_METRIC_KEYS = (
    "map_k_artist",
    "mrr_artist",
    "ndcg_k_artist",
    "recall_k_artist",
    "disc_artist",
    # n_queries_* counts are emitted for every ruler (0 when a ruler has no labeled population).
    "n_queries_artist",
    "n_queries_genre",
    "n_queries_head",
)

#: The SCORED (non-count) suffixed cells a class/medoid emits for this artist-only fixture — the
#: keys that form baseline/winner delta rows (n_queries_* counts are excluded from that machinery).
_SCORED_CLASS_METRIC_KEYS = ("map_k_artist", "mrr_artist", "ndcg_k_artist", "recall_k_artist", "disc_artist")


def _cfg(threshold: float) -> catalog_mod.SegConfigInput:
    return catalog_mod.SegConfigInput(
        backbone=_BACKBONE,
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _unit_axis(i: int) -> np.ndarray:
    v = np.zeros(4, dtype=np.float32)
    v[i] = 1.0
    return v


def _stream(axis: int, dist: float) -> np.ndarray:
    """Six unit rows (three on a basis axis, three at Euclidean distance ``dist``)."""
    u = _unit_axis(axis)
    theta = math.acos(1.0 - dist * dist / 2.0)
    other = _unit_axis((axis + 1) % 4)
    p = (u * math.cos(theta) + other * math.sin(theta)).astype(np.float32)
    return np.stack([u, u, u, p, p, p])


def _streams(song_ids=_SONGS) -> dict:
    return {(song, _BACKBONE): _stream(axis % 4, 0.5) for axis, song in enumerate(sorted(song_ids))}


def _register_songs(con, song_ids=_SONGS, artists=_ARTISTS) -> None:
    for song in song_ids:
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", artists[song]),
        )


def _build(compact_catalog_factory, con, out, *, song_ids=_SONGS, masks=None):
    """A durable single-class compact catalog over the corpus (all songs searchable by default)."""
    harness = compact_catalog_factory(
        con,
        out,
        streams=_streams(song_ids),
        configs=[_cfg(0.9)],
        song_ids=list(song_ids),
        masks=masks,
        run_id=_RUN,
    )
    # The research DB must know artists for run.py's load_all_songs(); the compact snapshot con
    # stays authoritative for catalog reads until run.py reopens it (single-writer rule).
    _register_songs(con, song_ids=song_ids)
    return harness


def test_medoid_producer_metrics_keys_match_a_segmented_class(compact_catalog_factory, con, tmp_path):
    """analyze_medoid_baseline emits the SAME cell keys a segmented class emits (exact-scope join)."""
    out = tmp_path / "m1"
    harness = _build(compact_catalog_factory, con, out)
    try:
        metrics = ca.analyze_medoid_baseline(
            harness.stream_store, backbone=_BACKBONE, song_ids=_SONGS, artists=_ARTISTS, k=10
        )
        assert metrics is not None
        assert tuple(sorted(metrics)) == tuple(sorted(_CLASS_METRIC_KEYS))
        for value in metrics.values():
            assert np.isfinite(value)
        assert metrics["map_k_artist"] >= 0.0 and metrics["map_k_artist"] <= 1.0
    finally:
        harness.close()


def test_zero_searchable_song_excluded_from_medoid_corpus(compact_catalog_factory, con, tmp_path):
    """A fully-silent song in song_ids is excluded from the baseline population + candidate search."""
    out = tmp_path / "m2"
    silent = np.zeros(6, dtype=np.uint8)  # whole stream silent -> zero-searchable song
    masks = {"s4": silent}
    harness = _build(compact_catalog_factory, con, out, masks=masks)
    try:
        # s4 is fully silent -> no medoid unit vector at all.
        obs = harness.stream_store.load_committed_observation("s4", _BACKBONE)
        assert observed_global_medoid_unit_vector(obs) is None
        # Baseline over the 4-song corpus (s4 excluded internally) equals the baseline over the
        # 3-song searchable corpus alone -> s4 never enters the baseline population or candidate set.
        full = ca.analyze_medoid_baseline(
            harness.stream_store, backbone=_BACKBONE, song_ids=_SONGS, artists=_ARTISTS, k=10
        )
        trimmed = ca.analyze_medoid_baseline(
            harness.stream_store, backbone=_BACKBONE, song_ids=("s1", "s2", "s3"), artists=_ARTISTS, k=10
        )
        assert full is not None and trimmed is not None
        for key in _CLASS_METRIC_KEYS:
            assert full[key] == pytest.approx(trimmed[key]), f"silent s4 leaked into medoid baseline {key}"
    finally:
        harness.close()


def _decode_rows(con, run_id):
    """Raw decode of analyze_metrics under run_id into {strategy_type: {strategy_key: {metric: value}}}."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for strategy_key, strategy_type, sim_metric, k, metric, value in con.execute(
        "SELECT strategy_key, strategy_type, sim_metric, k, metric, value "
        "FROM analyze_metrics WHERE run_id = ? ORDER BY strategy_type, strategy_key, metric",
        (run_id,),
    ).fetchall():
        assert sim_metric == "cosine" and k == 10
        out.setdefault(strategy_type, {}).setdefault(strategy_key, {})[str(metric)] = float(value)
    return out


def test_run_analyze_emits_one_global_pool_baseline_row_per_backbone(compact_catalog_factory, con, tmp_path):
    """The REAL run.py::_run_analyze path (MANDATORY baseline) persists one medoid baseline per backbone."""
    from scripts.embedding_research import run as run_mod

    out = tmp_path / "runpy-medoid"
    harness = _build(compact_catalog_factory, con, out)
    try:
        harness.handle.close()  # let run.py reopen the durable current.json read-only (single-writer)
        ret = run_mod._run_analyze(con, {"output_root": str(out), "backbones": [_BACKBONE], "k": 10}, run_id=_RUN)
        assert ret["song_count"] == len(_SONGS)
        decoded = _decode_rows(con, _RUN)
        medoid_keys = decoded.get(MEDOID_STRATEGY_TYPE, {})
        assert len(medoid_keys) == 1, "exactly ONE observed baseline identity per backbone"
        medoid_key = medoid_strategy_key_for(_BACKBONE)
        assert medoid_key in medoid_keys
        medoid_metrics = medoid_keys[medoid_key]
        # Cell alignment with a segmented class: same metric keys, same (cosine, k) scope.
        catalog_rows = decoded.get("catalog", {})
        assert len(catalog_rows) == 1  # single-class catalog fixture
        class_metrics = next(iter(catalog_rows.values()))
        assert set(medoid_metrics) == set(class_metrics) == set(_CLASS_METRIC_KEYS)
        assert medoid_key not in catalog_rows  # never a 'catalog' strategy row
    finally:
        harness.close()


def test_persisted_class_and_medoid_rows_yield_finite_baseline_deltas(compact_catalog_factory, con, tmp_path):
    """build_baseline_delta_rows over the persisted (class + global_pool) rows emits finite per-cell deltas."""
    from scripts.embedding_research import run as run_mod

    out = tmp_path / "runpy-deltas"
    harness = _build(compact_catalog_factory, con, out)
    try:
        harness.handle.close()
        run_mod._run_analyze(con, {"output_root": str(out), "backbones": [_BACKBONE], "k": 10}, run_id=_RUN)
        decoded = _decode_rows(con, _RUN)
        catalog_rows = decoded["catalog"]
        class_key = next(iter(catalog_rows))
        medoid_key = medoid_strategy_key_for(_BACKBONE)
        # Build the delta over the REAL winners loader (which carries each row's persisted
        # analyze_scope_v2 evaluation-corpus identity), NOT a hand-assembled identity-less frame —
        # the legacy identity-less structural match is gone under the corrective hard cut.
        from scripts.embedding_research.report._retrieval import query_winners_metrics

        winners = query_winners_metrics(con, run_id=_RUN)
        result = build_baseline_delta_rows(winners)
        matched = result.rows
        # Every segmented result cell (one per class metric key) gets a finite delta row.
        assert {r["metric"] for r in matched} == set(_SCORED_CLASS_METRIC_KEYS)
        assert {r["baseline_strategy_key"] for r in matched} == {medoid_key}
        assert {r["winner_strategy_key"] for r in matched} == {class_key}
        assert all(math.isfinite(float(r["delta"])) for r in matched)
        # The persisted class + medoid rows share the real run's equal comparable evaluation corpus,
        # so nothing is surfaced as an incomplete diagnostic.
        assert result.incomplete == ()
    finally:
        harness.close()
