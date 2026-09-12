"""R6 — one geometry decode, derive-before-score, unique representation scoring.

The analysis path must decode the committed geometry exactly once, never reload the
source stream, never segment inside the scorer, and must submit exactly one scorer
call per unique search representation (plus the separately identified baseline).
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import duckdb
import numpy as np

from scripts.embedding_research.common import threshold_analysis as ta
from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    GeometryRepresentationRoster,
    score_unique_geometry_representations,
)
from scripts.embedding_research.common.threshold_analysis import PRIMARY_EXPERIMENT
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.geometry import write_geometry
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tests._gram_evidence import SyntheticObservation, emit_evidence


def _record(con):
    stream = np.asarray([[1, 0], [1, 0], [0, 1], [0, 1], [1, 0], [0, 1]], dtype=np.float32)
    return write_geometry(SyntheticObservation(con, stream=stream), GeometryProfile.current(), "run-batch")


def _representation(representation_id: str, *, song_id: str = "song-1") -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id=song_id,
        backbone="backbone-a",
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]], dtype="<f4"),
        weights=np.asarray([1.0], dtype="<f8"),
        search_representation_id=representation_id,
        geometry_id="geometry-1",
        observation_id="observation-1",
        numerical_profile_digest="profile-1",
        mask_digest="mask-1",
        scoring_semantics_version=1,
        experiment=PRIMARY_EXPERIMENT,
    )


def test_one_geometry_load_and_no_stream_reload(monkeypatch) -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _record(con)
        calls = {"decode": 0}
        original = ta._verified_geometry_decode

        def spy(geometry_record):
            calls["decode"] += 1
            return original(geometry_record)

        monkeypatch.setattr(ta, "_verified_geometry_decode", spy)
        analysis = ta.analyze_all_thresholds(
            record, np.ones(record.matrix.shape[0], dtype=np.uint8), ta.dense_primary_threshold_request()
        )
        assert calls["decode"] == 1
        assert analysis.geometry_decode_count == 1
        assert analysis.stream_gather_count == 0
        assert len(analysis.results) == 171
        emit_evidence(
            "r6-one-decode.json",
            {
                "geometry_decode_count": calls["decode"],
                "stream_gather_count": analysis.stream_gather_count,
                "threshold_results": len(analysis.results),
            },
        )
    finally:
        con.close()


def test_no_segmentation_in_scorer() -> None:
    source = inspect.getsource(score_unique_geometry_representations)
    for forbidden in (
        "gram_from_stream",
        "derive_temporal_global_from_gram",
        "derive_all_temporal_global",
        "search_projection_from_gram",
    ):
        assert forbidden not in source, f"scorer reachable from {forbidden}"

    calls: list[object] = []

    def scoring(_query_vectors, _query_weights, view):
        calls.append(view)
        return SimpleNamespace(finite=True, score=0.5)

    roster = GeometryRepresentationRoster(
        representations=(_representation("rep-1"), _representation("rep-2", song_id="song-2"))
    )
    bundle = score_unique_geometry_representations(
        roster,
        {
            "query_vectors": np.asarray([[1.0, 0.0]], dtype=np.float32),
            "query_weights": np.asarray([1.0], dtype=np.float64),
        },
        scoring=scoring,
    )
    assert len(calls) == 2, "one scorer call per unique representation, no segmentation pass"
    assert bundle.segmentation_from_scorer_count == 0
    assert bundle.scorer_call_count == 2
    emit_evidence("r6-scorer-boundary.json", {"scorer_calls": len(calls), "segmentation_from_scorer_count": 0})


def test_representation_collapse_and_unique_scorer_count() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _record(con)
        analysis = ta.analyze_all_thresholds(
            record, np.ones(record.matrix.shape[0], dtype=np.uint8), ta.dense_primary_threshold_request()
        )
        classes = analysis.representation_classes
        canonical_indices = [int(item.canonical_threshold_index) for item in classes]
        assert canonical_indices == sorted(canonical_indices)
        for item in classes:
            assert item.canonical_threshold_index == min(item.member_threshold_indices)
        assert len({item.key for item in classes}) == len(classes)
        assert len(analysis.unique_search_representations) == len(classes)
        assert analysis.unique_representation_count == len(classes)

        reps = tuple(_representation(f"collapsed-{index}", song_id=f"song-{index}") for index in range(len(classes)))
        calls: list[object] = []

        def scoring(_query_vectors, _query_weights, view):
            calls.append(view)
            return SimpleNamespace(finite=True, score=1.0)

        bundle = score_unique_geometry_representations(
            GeometryRepresentationRoster(representations=reps),
            {
                "query_vectors": np.asarray([[1.0, 0.0]], dtype=np.float32),
                "query_weights": np.asarray([1.0], dtype=np.float64),
            },
            scoring=scoring,
        )
        assert len(calls) == len(classes)
        assert bundle.unique_representation_count == len(classes)
        assert bundle.scorer_call_count == len(classes)
        assert len(set(bundle.scores)) == len(classes)
        emit_evidence(
            "r6-collapse-unique-scorer.json",
            {
                "unique_representation_count": len(classes),
                "scorer_calls": len(calls),
                "member_threshold_total": sum(len(item.member_threshold_indices) for item in classes),
            },
        )
    finally:
        con.close()
