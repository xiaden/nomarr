"""Focused synthetic tests for the real geometry corpus owner (Plan K P2-S9)."""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    GeometryCorpusRequest,
    GeometrySongRequest,
    analyze_geometry_corpus,
)
from scripts.embedding_research.common.threshold_analysis import (
    SecondaryChebyshevRequest,
    analyze_secondary_all_thresholds,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry import GeometryIdentity, StaleRefused
from scripts.embedding_research.db.geometry_profile import GeometryProfile

pytestmark = pytest.mark.unit


class _Identity:
    mask_ref = "mask-ref"
    mask_digest = "mask-a"
    alignment_token = "align"
    audio_content_sha256 = "audio-digest"
    mask_semantics_version = "mask-v1"
    group_format_version = "group-v1"
    commit_sha256 = "commit-1"
    observation_group_sha256 = "commit-1"


class _StreamRecord:
    stream_ref = "stream-ref"
    fingerprint_sha256 = "stream-fingerprint"
    stream_payload_sha256 = "stream-payload"
    patch_count = 3
    embedding_dim = 2
    stream_dtype = "float32"
    stream_format_version = "stream-v1"
    embed_semantics_version = 1
    preprocess_fn = "preprocess"
    preprocess_version = "1"
    backbone_model_hash = "model"
    audio_params = "synthetic"
    provenance_source = "synthetic"
    provenance_assumption = "fixture"


class _Observation:
    identity = _Identity()
    identity.song_id = "song-1"
    identity.backbone = "backbone-a"
    stream_record = _StreamRecord()
    stream = np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    mask = np.ones(3, dtype=np.uint8)
    provenance_identity = "provenance"

    def __init__(self, con) -> None:
        self.con = con


class _Store:
    def __init__(self, observation) -> None:
        self.observation = observation
        self.loads = 0
        self.gathers: list[tuple[int, ...]] = []

    def load_committed_observation(self, _song_id, _backbone):
        self.loads += 1
        assert (_song_id, _backbone) == ("song-1", "backbone-a")
        return self.observation

    def batch_gather(self, _song_id, _backbone, indices, *, forbid_duplicates):
        assert forbid_duplicates is True
        values = tuple(indices)
        self.gathers.append(values)
        return np.asarray(self.observation.stream[list(values)], dtype=np.float32)


def _seed(con):
    observation = _Observation(con)
    record = write_geometry(observation, GeometryProfile.current(), "seed-run")
    identity = GeometryIdentity(
        "song-1",
        "backbone-a",
        "commit-1",
        record.identity.geometry_semantics_version,
        record.identity.numerical_profile_digest,
    )
    request = GeometryCorpusRequest(
        items=(
            GeometrySongRequest(
                "song-1",
                "backbone-a",
                identity,
                dict(record.evidence),
                artist="artist-a",
                genre="genre-a",
                head_label=("head-a",),
            ),
        ),
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        scoring_semantics_version=1,
        run_id="run-a",
        execution_id="execution-a",
        numerical_profile_digest=record.identity.numerical_profile_digest,
    )
    return observation, record, request


def _scorer(calls):
    def score(query, weights, candidate):
        calls.append((len(query), len(weights), len(candidate.vectors)))
        return SimpleNamespace(finite=True, score=0.5)

    return score


def test_real_owner_loads_decodes_derives_then_gathers_unique_representations() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, request = _seed(con)
    store = _Store(observation)
    calls: list[tuple[int, int, int]] = []
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer(calls)
    )

    # One load pins the observation for computation; the second is the mandatory
    # post-computation re-read (Plan P) that refuses a supersession before publication.
    assert store.loads == 2
    assert result.counters.geometry_load_count == 1
    assert result.counters.observation_load_count == 1
    assert result.counters.threshold_analysis_count == 1
    assert len(result.analyses) == 1
    assert len(result.analyses[0].results) == 171
    assert result.analyses[0].geometry_decode_count == 1
    assert result.analyses[0].unique_representation_count >= 1
    assert result.counters.source_gather_count == len(store.gathers)
    assert result.counters.scorer_call_count == len(calls)
    assert result.counters.segmentation_from_scorer_count == 0
    # Corrective semantics: a one-song corpus has no leave-one-out candidates, so the
    # query is explicitly non-comparable (never self-similarity) and is not scored.
    assert calls == []
    assert result.comparable is False
    assert result.candidates == ()
    assert result.scores is None
    assert result.baseline is not None
    assert result.queries[0].state.comparable is False
    assert "no_candidates" in result.queries[0].state.reasons
    assert result.noncomparable
    con.close()


def test_owner_zero_mask_is_empty_and_baseline_is_separate() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, request = _seed(con)
    observation.mask = np.zeros(3, dtype=np.uint8)
    store = _Store(observation)
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )
    # Zero searchable mass is explicit non-comparable evidence, not a silent drop.
    assert result.noncomparable
    assert all("no_searchable" in evidence.reasons for evidence in result.noncomparable)
    assert result.baseline is None
    assert result.scores is None
    assert result.candidates == ()
    assert result.counters.source_gather_count == 0
    assert result.queries[0].state.comparable is False
    assert result.queries[0].neighborhood == ()
    con.close()


def test_cross_experiment_identity_never_collapses() -> None:
    primary = dense_primary_threshold_request()
    secondary = SecondaryChebyshevRequest((1.0,))
    secondary_result = analyze_secondary_all_thresholds(
        np.asarray([[1, 0], [0, 1]], dtype=np.float32), np.ones(2, dtype=np.uint8), secondary
    )
    assert primary.experiment != secondary.experiment
    assert secondary_result.results[0].search.experiment == secondary.experiment
    assert secondary_result.results[0].search.experiment != primary.experiment


def test_supersession_refuses_before_result_publication() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, request = _seed(con)
    original = observation.identity.commit_sha256
    observation.identity.commit_sha256 = "commit-superseded"
    with pytest.raises(StaleRefused, match="requested geometry identity"):
        analyze_geometry_corpus(
            request, con=con, stream_store=_Store(observation), profile=GeometryProfile.current(), scoring=_scorer([])
        )
    assert observation.identity.commit_sha256 != original
    con.close()
