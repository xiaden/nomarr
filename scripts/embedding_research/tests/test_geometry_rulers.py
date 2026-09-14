"""Focused synthetic test for frozen geometry-evaluation scoring.

The geometry-owned ruler reduction now lives in the class-scoped normalized metrics
(covered by ``test_experiment_one_class_metrics.py``); the retired aggregate ruler
helper was hard-cut.  This module keeps the frozen-evaluation DTO scoring contract.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.bounded_scoring import BoundedScoreResult
from scripts.embedding_research.common.geometry_analysis import (
    FrozenGeometryEvaluation,
    FrozenSearchRepresentation,
    GeometryRepresentationRoster,
    score_unique_geometry_representations,
)

pytestmark = pytest.mark.unit


def _representation() -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id="song-a",
        backbone="effnet",
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        weights=np.ones(1, dtype=np.float64),
        search_representation_id="representation-a",
        geometry_id="geometry-a",
        observation_group_sha256="observation-a",
        numerical_profile_digest="profile-a",
        mask_digest="mask-a",
        scoring_semantics_version=1,
        experiment="temporal_global",
    )


def test_frozen_evaluation_dto_drives_comparability_and_bounded_scoring() -> None:
    def scorer(query, _weights, candidate):  # type: ignore[no-untyped-def]
        return BoundedScoreResult(
            score=0.5,
            numerator=1.0,
            denominator=2.0,
            finite=True,
            tie_policy="first_index",
            collision_policy="retain_all_candidate_segments",
            variant="first_index+retain_all_candidate_segments",
            scoring_semantics_version=1,
            n_source_rows=len(query),
            n_candidate_rows=len(candidate.vectors),
            winner_counts={0: 1.0},
            collisions=(),
            retained_count=1,
            dropped_count=0,
            trace_retained=False,
            trace=None,
            query_key_provenance=None,
            candidate_key_provenance=candidate.row_addresses,
            query_chunk_size=1,
            candidate_chunk_size=1,
            working_memory=64,
        )

    roster = GeometryRepresentationRoster((_representation(),))
    evaluation = FrozenGeometryEvaluation(
        evaluation_id="evaluation-a",
        query_vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        query_weights=np.ones(1, dtype=np.float64),
        eligible_song_ids=("song-a",),
        observation_evidence_digest="observation-a",
        comparable=False,
    )
    bundle = score_unique_geometry_representations(roster, evaluation, scorer)

    assert bundle.evaluation_comparable is False
    assert bundle.scores == {"representation-a": pytest.approx(0.5)}
    assert bundle.scorer_call_count == 1
    assert bundle.segmentation_from_scorer_count == 0
