"""Focused synthetic tests for Plan K P2-S6 geometry ruler aggregation.

These tests exercise the geometry-owned, CPU-only ruler reduction directly. They
prove that artist, genre, and frozen semantic-head rulers aggregate over their own
labeled populations (local missing-label exclusion, never an ``unknown`` bucket),
that every emitted value is finite and bounded, and that a baseline delta is
retained only when the evaluation identity is comparable. No alternate
vocabulary, real corpus, or segmentation runtime is involved.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from scripts.embedding_research.bounded_scoring import BoundedScoreResult
from scripts.embedding_research.common.geometry_analysis import (
    FrozenGeometryEvaluation,
    FrozenSearchRepresentation,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    _geometry_ruler_metrics,
    score_unique_geometry_representations,
)
from scripts.embedding_research.common.threshold_analysis import AllThresholdAnalysis
from scripts.embedding_research.db.geometry import GeometryIdentity

pytestmark = pytest.mark.unit


def _request(
    song_id: str,
    *,
    artist: object | None = None,
    genre: object | None = None,
    head_label: object | None = None,
) -> GeometrySongRequest:
    return GeometrySongRequest(
        song_id=song_id,
        backbone="effnet",
        geometry_identity=GeometryIdentity(song_id, "effnet", "commit-a", "geometry-v1", "profile-a"),
        observation_evidence={"observation_id": f"observation-{song_id}"},
        artist=artist,  # type: ignore[arg-type]
        genre=genre,  # type: ignore[arg-type]
        head_label=head_label,
    )


def _analysis(
    song_id: str,
    *,
    winner: float,
    baseline: float | None,
    comparable: bool = True,
    **labels: object | None,
) -> GeometrySongAnalysis:
    thresholds = AllThresholdAnalysis(
        experiment="temporal_global",
        geometry_id=f"geometry-{song_id}",
        observation_id=f"observation-{song_id}",
        profile_digest="profile-a",
        mask_digest="mask-a",
        results=(),
        geometry_semantics_version="geometry-v1",
        evaluation_id="evaluation-a",
        execution_id="execution-a",
    )
    scores = GeometryScoreBundle(
        scores={f"representation-{song_id}": winner},
        baseline_score=baseline,
        evaluation_comparable=comparable,
    )
    return GeometrySongAnalysis(_request(song_id, **labels), thresholds, GeometryRepresentationRoster(()), scores)


def _assert_finite(mapping: dict[str, float]) -> None:
    for value in mapping.values():
        assert math.isfinite(value)


def test_artist_genre_and_head_rulers_are_independent() -> None:
    analyses = (
        _analysis("song-a", winner=0.9, baseline=0.4, artist="art", genre=None, head_label=("h1", "h2")),
        _analysis("song-b", winner=0.5, baseline=0.2, artist="art", genre="genre", head_label=None),
        _analysis("song-c", winner=0.1, baseline=0.05, artist=None, genre="genre", head_label=("h1", "h2")),
    )

    artist_metrics, genre_metrics, head_metrics, per_song, baseline_deltas = _geometry_ruler_metrics(analyses)

    assert artist_metrics["n_songs"] == 2.0
    assert artist_metrics["missing_count"] == 1.0
    assert artist_metrics["mean_winner"] == pytest.approx(0.7)
    assert genre_metrics["n_songs"] == 2.0
    assert genre_metrics["missing_count"] == 1.0
    assert genre_metrics["mean_winner"] == pytest.approx(0.3)
    assert head_metrics["n_songs"] == 2.0
    assert head_metrics["missing_count"] == 1.0
    assert head_metrics["mean_winner"] == pytest.approx(0.5)

    # song-a is artist+head but has no genre; song-b is artist+genre but no head;
    # song-c is genre+head but no artist. Rulers never share a population.
    assert artist_metrics["active"] == 1.0
    assert genre_metrics["active"] == 1.0
    assert head_metrics["active"] == 1.0
    assert set(per_song) == {"song-a", "song-b", "song-c"}
    _assert_finite(artist_metrics)
    _assert_finite(genre_metrics)
    _assert_finite(head_metrics)
    _assert_finite(baseline_deltas)


def test_baseline_delta_retained_only_when_evaluation_is_comparable() -> None:
    analyses = (
        _analysis("song-a", winner=0.9, baseline=0.4, comparable=True, artist="art"),
        _analysis("song-b", winner=0.5, baseline=0.2, comparable=False, artist="art"),
    )

    artist_metrics, _genre, _head, per_song, baseline_deltas = _geometry_ruler_metrics(analyses)

    assert "baseline_delta" in per_song["song-a"]
    assert per_song["song-a"]["baseline_delta"] == pytest.approx(0.5)
    assert "baseline_delta" not in per_song["song-b"]
    assert per_song["song-b"]["comparable"] == 0.0
    assert artist_metrics["n_compared"] == 1.0
    assert artist_metrics["mean_delta"] == pytest.approx(0.5)
    assert baseline_deltas["artist"] == pytest.approx(0.5)


def test_missing_and_blank_labels_are_excluded_never_unknown() -> None:
    analyses = (
        _analysis("song-a", winner=0.9, baseline=0.4, artist=None, genre=None, head_label=("", "")),
        _analysis("song-b", winner=0.5, baseline=0.2, artist=None, genre=None, head_label="   "),
        _analysis("song-c", winner=0.3, baseline=0.1, artist="art", genre="genre", head_label=("h",)),
    )

    artist_metrics, genre_metrics, head_metrics, per_song, _deltas = _geometry_ruler_metrics(analyses)

    assert artist_metrics["n_songs"] == 1.0
    assert artist_metrics["missing_count"] == 2.0
    assert genre_metrics["active"] == 1.0
    assert genre_metrics["n_songs"] == 1.0
    assert genre_metrics["missing_count"] == 2.0
    assert head_metrics["active"] == 1.0
    assert head_metrics["n_songs"] == 1.0
    assert head_metrics["missing_count"] == 2.0
    # Per-song evidence is retained for every song regardless of ruler membership.
    assert set(per_song) == {"song-a", "song-b", "song-c"}


def test_inactive_ruler_emits_finite_guarded_zeros() -> None:
    analyses = (_analysis("song-a", winner=0.9, baseline=0.4, artist=None, genre=None, head_label=None),)

    artist_metrics, genre_metrics, head_metrics, _per_song, _deltas = _geometry_ruler_metrics(analyses)

    for metrics in (artist_metrics, genre_metrics, head_metrics):
        assert metrics["active"] == 0.0
        assert metrics["n_songs"] == 0.0
        assert metrics["n_compared"] == 0.0
        assert metrics["missing_count"] == 1.0
        assert metrics["mean_winner"] == 0.0
        assert metrics["mean_baseline"] == 0.0
        assert metrics["mean_delta"] == 0.0
        _assert_finite(metrics)


def _representation() -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id="song-a",
        backbone="effnet",
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        weights=np.ones(1, dtype=np.float64),
        search_representation_id="representation-a",
        geometry_id="geometry-a",
        observation_id="observation-a",
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
