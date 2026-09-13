"""Synthetic edge-contract tests for the corrective Gram-geometry surface.

Fills four confirmed coverage gaps left by the corrective repair:

* ``geometry_analysis._select_neighborhood`` search-identity tie-break / limit / absent-key skip.
* ``geometry_analysis._normalized_query_vectors`` empty-mask and zero-row filtering.
* ``identity_persistence.read_threshold_map_rows`` exact-scope isolation and row filtering.
* Zero / near-zero segment-centroid fixtures through ``derive_temporal_global_from_gram``.

Everything here is deterministic synthetic data: no audio, ONNX, CUDA, real corpus,
network, or source-control reads.  DuckDB is in-memory.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    _normalized_query_vectors,
    _select_neighborhood,
)
from scripts.embedding_research.db.identity_persistence import read_threshold_map_rows
from scripts.embedding_research.helpers.gram_segmentation import (
    GramRefusalError,
    derive_temporal_global_from_gram,
    gram_from_stream,
)

pytestmark = pytest.mark.unit


# ── shared synthetic representation fixture ────────────────────────────────────


def _rep(name: str) -> FrozenSearchRepresentation:
    """One minimal valid search representation keyed by its search identity."""
    return FrozenSearchRepresentation(
        song_id=f"song-{name}",
        backbone="effnet",
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        weights=np.ones(1, dtype=np.float64),
        search_representation_id=name,
        geometry_id=f"g-{name}",
        observation_group_sha256=f"o-{name}",
        numerical_profile_digest="profile",
        mask_digest="mask",
        scoring_semantics_version=1,
        experiment="temporal_global",
    )


# ── GAP 1: _select_neighborhood determinism ────────────────────────────────────


def test_select_neighborhood_ties_break_by_search_identity_ascending() -> None:
    scores = {"rep-c": 0.5, "rep-a": 0.5, "rep-b": 0.5}
    lookup = {name: _rep(name) for name in scores}

    first = _select_neighborhood(scores, lookup)
    # Same scores and identities, but a differently-inserted mapping order.
    reordered = {name: scores[name] for name in ("rep-b", "rep-c", "rep-a")}
    second = _select_neighborhood(reordered, {name: lookup[name] for name in reordered})

    assert [entry.search_representation_id for entry in first] == ["rep-a", "rep-b", "rep-c"]
    assert [entry.rank for entry in first] == [0, 1, 2]
    assert [entry.score for entry in first] == [0.5, 0.5, 0.5]
    assert first == second


def test_select_neighborhood_limit_caps_with_contiguous_ranks() -> None:
    lookup = {f"rep-{index:02d}": _rep(f"rep-{index:02d}") for index in range(8)}
    scores = {name: 1.0 - index * 0.1 for index, name in enumerate(lookup)}

    neighborhood = _select_neighborhood(scores, lookup, limit=3)

    assert len(neighborhood) == 3
    assert [entry.rank for entry in neighborhood] == [0, 1, 2]
    assert [entry.score for entry in neighborhood] == pytest.approx([1.0, 0.9, 0.8])


def test_select_neighborhood_skips_keys_absent_from_lookup() -> None:
    lookup = {"rep-a": _rep("rep-a"), "rep-c": _rep("rep-c")}
    scores = {"rep-a": 0.9, "rep-missing": 0.8, "rep-c": 0.7}

    neighborhood = _select_neighborhood(scores, lookup)

    assert [entry.search_representation_id for entry in neighborhood] == ["rep-a", "rep-c"]
    assert all(entry.search_representation_id != "rep-missing" for entry in neighborhood)


# ── GAP 2: _normalized_query_vectors ───────────────────────────────────────────


def test_normalized_query_vectors_all_zero_mask_is_empty() -> None:
    stream = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    mask = np.zeros(2, dtype=np.uint8)

    vectors, weights = _normalized_query_vectors(stream, mask)

    assert vectors.shape == (0, 2)
    assert vectors.dtype == np.float32
    assert weights.shape == (0,)
    assert weights.dtype == np.float64


def test_normalized_query_vectors_drops_zero_rows_and_returns_canonical_arrays() -> None:
    # Row 1 is searchable but all-zero, so the norms > 0 filter must drop it.
    stream = np.asarray([[3.0, 4.0], [0.0, 0.0], [0.0, 2.0]], dtype=np.float32)
    mask = np.ones(3, dtype=np.uint8)

    vectors, weights = _normalized_query_vectors(stream, mask)

    assert vectors.shape == (2, 2)
    assert vectors.dtype == np.float32
    assert np.isfinite(vectors).all()
    assert not np.any(np.all(vectors == 0.0, axis=1))
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert weights.dtype == np.float64
    assert weights.shape == (2,)
    assert weights.tolist() == [1.0, 1.0]


# ── GAP 3: read_threshold_map_rows exact scope and filtering ───────────────────

_ANALYSIS_COLUMNS = (
    "run_id, geometry_id, observation_group_sha256, geometry_semantics_version, numerical_profile_digest,"
    " threshold_id, structural_identity, search_representation_id, evaluation_id,"
    " scoring_semantics_version, execution_id, metric, value, evidence_json, created_at_ms"
)


def _insert_threshold_row(
    con: Any,
    *,
    run_id: str = "run-a",
    evaluation_id: str = "eval-a",
    execution_id: str = "exec-a",
    threshold_id: str,
    evidence_json: str | None,
    metric: str = "total_searchable",
) -> None:
    con.execute(
        f"INSERT INTO geometry_analysis_records ({_ANALYSIS_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            run_id,
            "g1",
            "obs-1",
            "gram-v1",
            "profile-digest",
            threshold_id,
            "struct-1",
            "rep-1",
            evaluation_id,
            1,
            execution_id,
            metric,
            0.0,
            evidence_json,
            1,
        ],
    )


def _threshold_evidence(**overrides: Any) -> str:
    evidence: dict[str, Any] = {"role": "threshold", "song_id": "s1", "backbone": "effnet"}
    evidence.update(overrides)
    return json.dumps(evidence)


def test_read_threshold_map_rows_isolates_exact_scope(con) -> None:
    good = _threshold_evidence()
    _insert_threshold_row(con, threshold_id="t-exact", evidence_json=good)
    # Decoy on each scope axis; each would be returned if scoping were leaky.
    _insert_threshold_row(con, evaluation_id="eval-b", threshold_id="t-eval", evidence_json=good)
    _insert_threshold_row(con, execution_id="exec-b", threshold_id="t-exec", evidence_json=good)
    _insert_threshold_row(con, run_id="run-b", threshold_id="t-run", evidence_json=good)

    rows = read_threshold_map_rows(con, run_id="run-a", evaluation_id="eval-a", execution_id="exec-a")

    assert [row["threshold_id"] for row in rows] == ["t-exact"]


def test_read_threshold_map_rows_skips_wrong_metric_empty_and_non_threshold_evidence(con) -> None:
    _insert_threshold_row(con, threshold_id="t-metric", evidence_json=_threshold_evidence(), metric="corpus")
    _insert_threshold_row(con, threshold_id="t-empty", evidence_json="")
    _insert_threshold_row(con, threshold_id="t-nondict", evidence_json="[]")
    _insert_threshold_row(con, threshold_id="t-role", evidence_json=json.dumps({"role": "corpus"}))
    _insert_threshold_row(con, threshold_id="t-ok", evidence_json=_threshold_evidence())

    rows = read_threshold_map_rows(con, run_id="run-a", evaluation_id="eval-a", execution_id="exec-a")

    assert [row["threshold_id"] for row in rows] == ["t-ok"]


def test_read_threshold_map_rows_orders_by_threshold_and_maps_comparable(con) -> None:
    _insert_threshold_row(
        con,
        threshold_id="t-010",
        evidence_json=_threshold_evidence(song_id="s2", comparable=False),
    )
    _insert_threshold_row(con, threshold_id="t-002", evidence_json=_threshold_evidence(song_id="s1"))
    _insert_threshold_row(
        con,
        threshold_id="t-100",
        evidence_json=_threshold_evidence(song_id="s3", comparable=True),
    )

    rows = read_threshold_map_rows(con, run_id="run-a", evaluation_id="eval-a", execution_id="exec-a")

    assert [row["threshold_id"] for row in rows] == ["t-002", "t-010", "t-100"]
    by_id = {row["threshold_id"]: row for row in rows}
    assert set(by_id["t-002"]) == {
        "song_id",
        "backbone",
        "threshold_id",
        "structural_identity",
        "search_representation_id",
        "comparable",
    }
    assert by_id["t-002"]["song_id"] == "s1"
    assert by_id["t-002"]["backbone"] == "effnet"
    # Absent comparable defaults to True; an explicit False is preserved.
    assert by_id["t-002"]["comparable"] is True
    assert by_id["t-100"]["comparable"] is True
    assert by_id["t-010"]["comparable"] is False


# ── GAP 4: zero / near-zero segment-centroid fixtures ──────────────────────────


def _assert_coherent(result: Any, count: int) -> None:
    assert np.isfinite(result.threshold)
    assert result.segments
    for segment in result.segments:
        assert type(segment.start_idx) is int
        assert type(segment.end_idx) is int
        assert 0 <= segment.start_idx <= segment.end_idx <= count
        absorbed = list(segment.absorbed_indices)
        assert all(0 <= index < count for index in absorbed)
        assert absorbed == sorted(absorbed)


def test_derive_temporal_global_zero_centroid_segment_is_coherent() -> None:
    # First row normalizes to an all-zero row, so the active segment opens on a
    # zero-norm centroid and exercises the _row_distance centroid_norm == 0 branch.
    stream = np.asarray([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)

    result = derive_temporal_global_from_gram(gram, 0)

    _assert_coherent(result, stream.shape[0])


def test_derive_temporal_global_near_zero_gram_stays_finite_or_refuses() -> None:
    stream = np.asarray([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)
    assert gram.dtype == np.dtype("<f4")
    assert gram.flags.c_contiguous
    assert not gram.flags.writeable

    scaled = np.asarray(gram * np.float32(np.finfo(np.float32).tiny), dtype="<f4", order="C")
    # Canonical stored-Gram round trip yields a non-writeable float32 matrix.
    loaded = np.frombuffer(scaled.tobytes(order="C"), dtype="<f4").reshape(scaled.shape)
    loaded.setflags(write=False)
    assert loaded.dtype == np.dtype("<f4")
    assert loaded.flags.c_contiguous
    assert not loaded.flags.writeable

    try:
        result = derive_temporal_global_from_gram(loaded, 0)
    except GramRefusalError:
        return
    _assert_coherent(result, loaded.shape[0])
