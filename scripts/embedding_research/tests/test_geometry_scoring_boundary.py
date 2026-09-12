"""Synthetic tests for the Plan K bounded geometry scoring boundary."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.bounded_scoring import BoundedScoreResult
from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    GeometryRepresentationRoster,
    score_unique_geometry_representations,
)


def _representation(name: str, *, baseline: bool = False) -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id="song-a",
        backbone="effnet",
        source_indices=(0, 1),
        vectors=np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        weights=np.ones(2, dtype=np.float64),
        search_representation_id=name,
        geometry_id="geometry-a",
        observation_id="observation-a",
        numerical_profile_digest="profile-a",
        mask_digest="mask-a",
        scoring_semantics_version=1,
        experiment="temporal_global",
        is_observed_baseline=baseline,
    )


def test_unique_representations_are_scored_once_and_baseline_is_separate() -> None:
    calls: list[object] = []

    def scorer(query, _weights, candidate):
        calls.append(candidate)
        return BoundedScoreResult(
            score=0.75,
            numerator=1.5,
            denominator=2.0,
            finite=True,
            tie_policy="first_index",
            collision_policy="retain_all_candidate_segments",
            variant="first_index+retain_all_candidate_segments",
            scoring_semantics_version=1,
            n_source_rows=len(query),
            n_candidate_rows=len(candidate.vectors),
            winner_counts={0: 2.0},
            collisions=(),
            retained_count=2,
            dropped_count=0,
            trace_retained=False,
            trace=None,
            query_key_provenance=None,
            candidate_key_provenance=candidate.row_addresses,
            query_chunk_size=1,
            candidate_chunk_size=1,
            working_memory=64,
        )

    result = score_unique_geometry_representations(
        GeometryRepresentationRoster(
            representations=(_representation("rep-a"), _representation("rep-b")),
            observed_baseline=_representation("baseline", baseline=True),
        ),
        {"query_vectors": [[1.0, 0.0]], "query_weights": [1.0]},
        scoring=scorer,
    )

    assert len(calls) == 3
    assert result.scorer_call_count == 3
    assert result.unique_representation_count == 2
    assert result.source_gather_count == 3
    assert result.segmentation_from_scorer_count == 0
    assert set(result.scores) == {"rep-a", "rep-b"}
    assert result.baseline_representation_id == "baseline"
    assert result.baseline_score == pytest.approx(0.75)


def test_boundary_rejects_nonfinite_transient_query_payload() -> None:
    with pytest.raises(ValueError, match="finite"):
        score_unique_geometry_representations(
            GeometryRepresentationRoster(representations=(_representation("rep-a"),)),
            {"query_vectors": [[np.nan, 0.0]], "query_weights": [1.0]},
        )
