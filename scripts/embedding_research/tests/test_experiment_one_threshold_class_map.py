"""Focused synthetic tests for the Experiment One threshold-class result layer (Plan A Phase 2).

They prove the hard-cut contract for the normalized result surfaces: one
``(run, execution_id, evaluation_id, threshold_index)`` map row per configured threshold
regardless of collapse, per-``(song, threshold)`` structural/search evidence in O(N x T),
exact per-threshold searchable counts (never a max across the sweep), zero duplicate
structural identities, and no retrieval metrics in the structural surface.  No real corpus,
model, audio, ONNX, or CUDA is involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    GeometryCorpusRequest,
    GeometrySongRequest,
    analyze_geometry_corpus,
    write_geometry_corpus_analysis,
)
from scripts.embedding_research.common.threshold_analysis import dense_primary_threshold_request
from scripts.embedding_research.db import (
    ensure_schema,
    read_threshold_class_map,
    read_threshold_structural,
    write_geometry,
)
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile

pytestmark = pytest.mark.unit

_RUN_ID = "run-class-map"
_EVALUATION_ID = "evaluation-class-map"
_EXECUTION_ID = "execution:run-class-map:backbone-a"
_BACKBONE = "backbone-a"
_THRESHOLDS = 171

_STREAMS = {
    "song-1": [[1, 0], [0, 1], [1, 1]],
    "song-2": [[1, 1], [0, 1], [1, 0]],
    "song-3": [[1, 1], [1, 0], [0, 1]],
}


class _Identity:
    mask_ref = "mask-ref"
    mask_digest = "mask-a"
    alignment_token = "align"
    audio_content_sha256 = "audio-digest"
    mask_semantics_version = "mask-v1"
    group_format_version = "group-v1"
    patch_count = 3


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
    stream_record = _StreamRecord()
    provenance_identity = "provenance"
    mask = np.ones(3, dtype=np.uint8)

    def __init__(self, con, song_id: str) -> None:
        self.con = con
        self.identity = _Identity()
        self.identity.song_id = song_id
        self.identity.backbone = _BACKBONE
        group = f"group-{song_id}"
        self.identity.commit_sha256 = group
        self.identity.observation_group_sha256 = group
        self.stream = np.asarray(_STREAMS[song_id], dtype=np.float32)


class _Store:
    def __init__(self, observations) -> None:
        self.observations = {observation.identity.song_id: observation for observation in observations}

    def load_committed_observation(self, song_id, backbone):
        assert backbone == _BACKBONE
        return self.observations[song_id]

    def batch_gather(self, song_id, backbone, indices, *, forbid_duplicates):
        assert forbid_duplicates is True
        assert backbone == _BACKBONE
        observation = self.observations[song_id]
        return np.asarray(observation.stream[list(indices)], dtype=np.float32)


def _scorer():
    def score(_query, _weights, _candidate):
        return SimpleNamespace(finite=True, score=0.5)

    return score


def _seed(con, song_ids: tuple[str, ...]):
    observations = [_Observation(con, song_id) for song_id in song_ids]
    items = []
    records = {}
    for observation in observations:
        song_id = observation.identity.song_id
        record = write_geometry(observation, GeometryProfile.current(), _RUN_ID)
        records[song_id] = record
        items.append(
            GeometrySongRequest(
                song_id,
                _BACKBONE,
                GeometryIdentity(
                    song_id,
                    _BACKBONE,
                    observation.identity.observation_group_sha256,
                    record.identity.geometry_semantics_version,
                    record.identity.numerical_profile_digest,
                ),
                dict(record.evidence),
                artist=f"artist-{song_id}",
                genre=f"genre-{song_id}",
                head_label=(f"head-{song_id}",),
            )
        )
    request = GeometryCorpusRequest(
        items=tuple(items),
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id=_EVALUATION_ID,
        scoring_semantics_version=1,
        run_id=_RUN_ID,
        execution_id=_EXECUTION_ID,
        numerical_profile_digest=records[song_ids[0]].identity.numerical_profile_digest,
    )
    return observations, request


def test_a_171_threshold_publication_is_one_map_row_per_threshold_and_linear_structural() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, request = _seed(con, ("song-1", "song-2", "song-3"))
    result = analyze_geometry_corpus(
        request,
        con=con,
        stream_store=_Store(observations),
        profile=GeometryProfile.current(),
        scoring=_scorer(),
    )
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    # In-memory surfaces: exactly one map row per configured threshold even when equal
    # scoring preimages collapse the class, and structural rows O(N x T).
    assert len(result.threshold_class_map) == _THRESHOLDS
    assert len(result.threshold_structural) == len(observations) * _THRESHOLDS
    assert len(result.threshold_structural) != _THRESHOLDS * _THRESHOLDS

    class_rows = read_threshold_class_map(con, run_id=_RUN_ID)
    structural_rows = read_threshold_structural(con, run_id=_RUN_ID)

    assert len(class_rows) == _THRESHOLDS
    assert len(structural_rows) == len(observations) * _THRESHOLDS
    # Never O(N x T^2): the result layer must not cross product threshold contexts.
    assert len(structural_rows) < _THRESHOLDS * _THRESHOLDS

    # Exactly one row per (run, execution_id, evaluation_id, threshold_index).
    class_identities = [
        (row["run_id"], row["execution_id"], row["evaluation_id"], row["threshold_index"]) for row in class_rows
    ]
    assert len(class_identities) == len(set(class_identities)) == _THRESHOLDS
    assert {row["threshold_index"] for row in class_rows} == set(range(_THRESHOLDS))

    # Zero duplicate (run, evaluation_id, song_id, threshold_index) structural identities.
    structural_identities = [
        (row["run_id"], row["evaluation_id"], row["song_id"], row["threshold_index"]) for row in structural_rows
    ]
    assert len(structural_identities) == len(set(structural_identities))

    # Structural rows carry structural/search evidence only, never retrieval metrics.
    forbidden = {"winner_score", "baseline_score", "baseline_delta", "neighborhood", "per_song_metrics", "map_10"}
    assert forbidden.isdisjoint(structural_rows[0])
    assert structural_rows[0]["backbone"] == _BACKBONE
    assert all(row["search_representation_id"] for row in structural_rows)

    con.close()


def test_per_threshold_searchable_count_is_exact_never_max_across_sweep() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, request = _seed(con, ("song-1", "song-2", "song-3"))
    result = analyze_geometry_corpus(
        request,
        con=con,
        stream_store=_Store(observations),
        profile=GeometryProfile.current(),
        scoring=_scorer(),
    )
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    # Expected exact count per (song, threshold) straight from each ThresholdAnalysisResult.
    ordered_items = sorted(request.items, key=lambda item: (item.song_id, item.backbone))
    expected: dict[tuple[str, int], int] = {}
    for item, analysis in zip(ordered_items, result.analyses, strict=True):
        for item_result in analysis.results:
            expected[(item.song_id, int(item_result.threshold.index))] = int(item_result.search.total_searchable)

    # At least one song has genuinely varying counts across thresholds, so a max-across-sweep
    # value would be caught by the exact comparison below.
    song_1_counts = {value for (song_id, _index), value in expected.items() if song_id == "song-1"}
    assert len(song_1_counts) > 1

    structural_rows = read_threshold_structural(con, run_id=_RUN_ID)
    for row in structural_rows:
        key = (row["song_id"], int(row["threshold_index"]))
        assert row["searchable_count"] == expected[key]

    con.close()
