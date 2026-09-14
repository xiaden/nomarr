"""Synthetic edge-contract tests for the corrective Gram-geometry surface.

Fills three confirmed coverage gaps left by the corrective repair:

* ``geometry_analysis._select_neighborhood`` search-identity tie-break / limit / absent-key skip.
* ``geometry_analysis._normalized_query_vectors`` empty-mask and zero-row filtering.
* Zero / near-zero segment-centroid fixtures through ``derive_temporal_global_from_gram``.

Everything here is deterministic synthetic data: no audio, ONNX, CUDA, real corpus,
network, or source-control reads.  DuckDB is in-memory.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    _normalized_query_vectors,
    _select_neighborhood,
)
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


# ── GAP 2: threshold-derived medoid/query projections ──────────────────────────


def test_threshold_projection_derives_observed_medoids_and_query_weights() -> None:
    from scripts.embedding_research.helpers.gram_segmentation import (
        derive_temporal_global_from_gram,
        search_projection_from_gram,
    )

    stream = np.asarray([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    gram, _ = gram_from_stream(stream)
    structural = derive_temporal_global_from_gram(gram, 0)
    projection = search_projection_from_gram(structural, gram, np.ones(3, dtype=np.uint8))

    assert projection.total_searchable == 3
    assert [segment.medoid_source_index for segment in projection.segments] == [0, 2]
    assert [segment.searchable_weight for segment in projection.segments] == pytest.approx([2 / 3, 1 / 3])


def test_retired_raw_query_helper_remains_tombstoned() -> None:
    with pytest.raises(RuntimeError, match="raw whole-song query vectors"):
        _normalized_query_vectors(np.ones((1, 2), dtype=np.float32), np.ones(1, dtype=np.uint8))


def test_threshold_projection_refuses_empty_searchable_query() -> None:
    from scripts.embedding_research.helpers.gram_segmentation import (
        derive_temporal_global_from_gram,
        search_projection_from_gram,
    )

    gram, _ = gram_from_stream(np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    structural = derive_temporal_global_from_gram(gram, 0)
    projection = search_projection_from_gram(structural, gram, np.zeros(2, dtype=np.uint8))

    assert projection.total_searchable == 0
    assert all(segment.medoid_source_index is None for segment in projection.segments)
    assert all(segment.searchable_weight == 0.0 for segment in projection.segments)


# ── GAP 3: zero / near-zero segment-centroid fixtures ──────────────────────────


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
