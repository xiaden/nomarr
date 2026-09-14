"""Normalized Experiment One result readback (Plan A Phase 6).

Proves the symmetric read path for the hard-cut result layer: the normalized reader
reconstructs the class-scoped result from the flat surfaces (fixed evaluation corpus,
threshold class map, threshold structural evidence, class/baseline aggregate/per-query/
neighborhood metrics, head-label provenance and the ONE compact provenance row) under the
exact ten-axis identity, and refuses every corruption instead of consulting the
removed nested ``role="corpus"`` evidence shape or ``geometry_analysis_records``.

* **exact round-trip** — every written normalized field is read back equal to the
  in-memory computation for a bounded synthetic fixture.
* **B** — the T1 / T2 metric distinction survives readback.
* **C** — two threshold-map rows sharing one class survive readback.
* **E** — a non-comparable class retains its canonical reasons and emits no partial metrics.
* **L** — a report payload with two threshold points and exactly one fixed baseline survives
  threshold -> class -> metric readback.
* **fail-closed** — duplicate metric rows, non-finite values, duplicate/self-referential
  neighborhood rows, an unknown reason, an empty required surface, and a missing
  invocation obligation/terminal are all refused.

No real corpus, model, audio, ONNX, or CUDA is involved.
"""

from __future__ import annotations

from dataclasses import asdict

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    GeometryAnalysisCounters,
    GeometryBaselineAggregateMetric,
    GeometryBaselineNeighborhood,
    GeometryBaselineQueryMetric,
    GeometryCandidate,
    GeometryClassAggregateMetric,
    GeometryClassNeighborhood,
    GeometryClassQueryMetric,
    GeometryCorpusAnalysis,
    GeometryCorpusHypothesis,
    GeometryEvaluationCorpusEntry,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    GeometryThresholdClassRow,
    GeometryThresholdStructuralRow,
    _geometry_axes_payload,
    build_geometry_corpus_identity,
    read_geometry_corpus_analysis_normalized,
    write_geometry_corpus_analysis,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    AnalysisEvidenceIdentity,
    SearchRepresentation,
    StructuralIdentity,
    ThresholdAnalysisResult,
    ThresholdSpec,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.analyze_scope import record_analyze_invocation
from scripts.embedding_research.db.geometry import GeometryIdentity, IntegrityRefused
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.helpers.corpus_identity import RepresentationState

pytestmark = pytest.mark.unit

_RUN_ID = "run-readback"
_EXECUTION_ID = "execution:run-readback:backbone-a"
_EVALUATION_ID = "evaluation-readback"
_BACKBONE = "backbone-a"
_SONG_ID = "song-1"


# ---------------------------------------------------------------------------
# Bounded synthetic geometry fixture (single song, one committed Gram)
# ---------------------------------------------------------------------------


class _Identity:
    song_id = _SONG_ID
    backbone = _BACKBONE
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
    audio_params = "audio"
    provenance_source = "synthetic"
    provenance_assumption = "fixture"


class _Observation:
    identity = _Identity()
    stream_record = _StreamRecord()
    stream = np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32)
    provenance_identity = "provenance"

    def __init__(self, con) -> None:
        self.con = con


def _seed_geometry(con):
    return write_geometry(_Observation(con), GeometryProfile.current(), "seed-run")


def _representation(record, *, name: str, baseline: bool = False) -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id=record.identity.song_id,
        backbone=record.identity.backbone,
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
        weights=np.ones(1, dtype=np.float64),
        search_representation_id=name,
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        numerical_profile_digest=record.identity.numerical_profile_digest,
        mask_digest="mask-a",
        scoring_semantics_version=1,
        experiment="temporal_global",
        is_observed_baseline=baseline,
    )


def _rich_corpus(record) -> GeometryCorpusAnalysis:
    """One bounded corpus with controlled normalized surfaces across four thresholds/classes."""
    threshold = ThresholdSpec(0, 0.30, "temporal_global:threshold:0:0.30")
    structural = StructuralIdentity(threshold.threshold_id, 0, (), (), "structural-a")
    search = SearchRepresentation(
        structural_identity=structural.identity,
        medoid_source_indices=(0,),
        searchable_weights=(1.0,),
        total_searchable=3,
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        profile_digest=record.identity.numerical_profile_digest,
        mask_digest="mask-a",
        scoring_semantics_version=1,
        experiment="temporal_global",
        search_representation_id="representation-a",
    )
    analysis = AllThresholdAnalysis(
        experiment="temporal_global",
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        profile_digest=record.identity.numerical_profile_digest,
        mask_digest="mask-a",
        results=(ThresholdAnalysisResult(threshold, structural, search, None),),
        geometry_semantics_version=record.identity.geometry_semantics_version,
        evaluation_id=_EVALUATION_ID,
        execution_id=_EXECUTION_ID,
    )
    baseline = _representation(record, name="baseline-a", baseline=True)
    roster = GeometryRepresentationRoster((_representation(record, name="representation-a"),), baseline)
    scores = GeometryScoreBundle(
        scores={"representation-a": 0.5},
        baseline_score=0.25,
        baseline_representation_id="baseline-a",
        evaluation_comparable=True,
    )
    request = GeometrySongRequest(
        song_id=record.identity.song_id,
        backbone=record.identity.backbone,
        geometry_identity=GeometryIdentity(
            record.identity.song_id,
            record.identity.backbone,
            record.identity.observation_group_sha256,
            record.identity.geometry_semantics_version,
            record.identity.numerical_profile_digest,
        ),
        observation_evidence={"song_id": record.identity.song_id, "backbone": record.identity.backbone},
    )
    query = GeometrySongAnalysis(
        request=request,
        thresholds=analysis,
        roster=roster,
        scores=scores,
        state=RepresentationState(True, True, True, ()),
        neighborhood=(),
        baseline_neighborhood=(),
        threshold_id=threshold.threshold_id,
        collapse_class_id="class-t1",
    )
    ruler = {
        "active": 1.0,
        "n_songs": 1.0,
        "n_compared": 1.0,
        "missing_count": 0.0,
        "mean_winner": 0.5,
        "mean_baseline": 0.25,
        "mean_delta": 0.25,
    }
    hypothesis = GeometryCorpusHypothesis(
        threshold_id=threshold.threshold_id,
        collapse_class_id="class-t1",
        members=(
            GeometryCandidate(
                roster.representations[0],
                query.state,
                structural.identity,
                (threshold.index,),
                3,
            ),
        ),
    )
    return GeometryCorpusAnalysis(
        run_id=_RUN_ID,
        execution_id=_EXECUTION_ID,
        experiment="temporal_global",
        evaluation_id=_EVALUATION_ID,
        numerical_profile_digest=record.identity.numerical_profile_digest,
        scoring_semantics_version=1,
        analyses=(analysis,),
        roster=roster,
        scores=scores,
        baseline=baseline,
        artist_metrics=dict(ruler),
        genre_metrics=dict(ruler),
        head_metrics=dict(ruler),
        per_song_metrics={record.identity.song_id: {"winner_score": 0.5, "baseline_delta": 0.25}},
        baseline_deltas={"artist": 0.25},
        comparable=True,
        counters=GeometryAnalysisCounters(1, 1, 1, 1, 1, 1, 0),
        evaluation_corpus=(
            GeometryEvaluationCorpusEntry(
                song_id=record.identity.song_id,
                backbone=record.identity.backbone,
                geometry_id=record.geometry_id,
                observation_group_sha256=record.identity.observation_group_sha256,
                numerical_profile_digest=record.identity.numerical_profile_digest,
                searchable_count=3,
                comparable=True,
                reasons=(),
                baseline_valid=True,
            ),
        ),
        # Four thresholds: 0 and 1 share class-t1, 2 is class-t2, 3 is the non-comparable class.
        threshold_class_map=(
            GeometryThresholdClassRow(0, "t-0", 0.30, "class-t1", True, ()),
            GeometryThresholdClassRow(1, "t-1", 0.31, "class-t1", True, ()),
            GeometryThresholdClassRow(2, "t-2", 0.32, "class-t2", True, ()),
            GeometryThresholdClassRow(3, "t-3", 0.33, "class-nc", False, ("zero_searchable",)),
        ),
        threshold_structural=(
            GeometryThresholdStructuralRow(
                record.identity.song_id,
                record.identity.backbone,
                0,
                "t-0",
                "struct-a",
                "rep-a",
                3,
                True,
                True,
                True,
                (),
            ),
            GeometryThresholdStructuralRow(
                record.identity.song_id,
                record.identity.backbone,
                1,
                "t-1",
                "struct-a",
                "rep-a",
                3,
                True,
                True,
                True,
                (),
            ),
            GeometryThresholdStructuralRow(
                record.identity.song_id,
                record.identity.backbone,
                2,
                "t-2",
                "struct-b",
                "rep-b",
                3,
                True,
                True,
                True,
                (),
            ),
            GeometryThresholdStructuralRow(
                record.identity.song_id,
                record.identity.backbone,
                3,
                "t-3",
                "struct-nc",
                "rep-nc",
                0,
                False,
                True,
                False,
                ("zero_searchable",),
            ),
        ),
        # B: class-t1 and class-t2 carry distinct metric values.
        class_aggregate_metrics=(
            GeometryClassAggregateMetric("class-t1", "artist", "mrr", 10, 0.9, 1, 0),
            GeometryClassAggregateMetric("class-t1", "genre", "mrr", 10, 0.8, 1, 0),
            GeometryClassAggregateMetric("class-t2", "artist", "mrr", 10, 0.1, 1, 0),
            GeometryClassAggregateMetric("class-t2", "genre", "mrr", 10, 0.2, 1, 0),
        ),
        class_query_metrics=(
            GeometryClassQueryMetric("class-t1", record.identity.song_id, "artist", "mrr", 10, 0.9, "defined"),
            GeometryClassQueryMetric("class-t2", record.identity.song_id, "artist", "mrr", 10, 0.1, "defined"),
        ),
        class_neighborhoods=(
            GeometryClassNeighborhood("class-t1", record.identity.song_id, "song-2", 0, 0.9),
            GeometryClassNeighborhood("class-t2", record.identity.song_id, "song-2", 0, 0.1),
        ),
        # L: exactly one fixed baseline block, independent of the threshold points.
        baseline_aggregate_metrics=(
            GeometryBaselineAggregateMetric(_BACKBONE, "artist", "mrr", 10, 0.25, 1, 0),
            GeometryBaselineAggregateMetric(_BACKBONE, "genre", "mrr", 10, 0.20, 1, 0),
        ),
        baseline_query_metrics=(
            GeometryBaselineQueryMetric(_BACKBONE, record.identity.song_id, "artist", "mrr", 10, 0.25, "defined"),
        ),
        baseline_neighborhoods=(GeometryBaselineNeighborhood(_BACKBONE, record.identity.song_id, "song-3", 0, 0.2),),
        queries=(query,),
        hypotheses=(hypothesis,),
    )


def _seeded():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _rich_corpus(record)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)
    identity = build_geometry_corpus_identity(result)
    return con, record, result, identity


# ---------------------------------------------------------------------------
# Exact round-trip: readback == in-memory computation
# ---------------------------------------------------------------------------


def test_exact_round_trip_equals_in_memory_computation() -> None:
    con, _record, result, identity = _seeded()
    readback = read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)

    assert readback.run_id == _RUN_ID
    assert set(readback.evaluation_corpus) == set(result.evaluation_corpus)
    assert set(readback.threshold_class_map) == set(result.threshold_class_map)
    assert set(readback.threshold_structural) == set(result.threshold_structural)
    assert set(readback.class_aggregate_metrics) == set(result.class_aggregate_metrics)
    assert set(readback.class_query_metrics) == set(result.class_query_metrics)
    assert set(readback.class_neighborhoods) == set(result.class_neighborhoods)
    assert set(readback.baseline_aggregate_metrics) == set(result.baseline_aggregate_metrics)
    assert set(readback.baseline_query_metrics) == set(result.baseline_query_metrics)
    assert set(readback.baseline_neighborhoods) == set(result.baseline_neighborhoods)

    assert readback.provenance.evidence_mode == result.evidence_mode
    assert readback.provenance.synthetic_only is True
    assert readback.provenance.comparable is result.comparable
    assert readback.provenance.execution_id == _EXECUTION_ID
    assert readback.provenance.evaluation_id == _EVALUATION_ID
    assert readback.provenance.experiment == "temporal_global"
    assert readback.provenance.counters == asdict(result.counters)
    assert readback.provenance.geometry_axes == tuple(_geometry_axes_payload(result))
    assert readback.provenance.head_evidence_provenance == result.head_evidence_provenance
    # Synthetic fixtures carry no frozen head-suite provenance rows.
    assert readback.head_label_provenance == ()
    con.close()


# ---------------------------------------------------------------------------
# B — T1 / T2 metric distinction survives readback
# ---------------------------------------------------------------------------


def test_readback_retains_t1_t2_metric_distinction() -> None:
    con, _record, _result, identity = _seeded()
    readback = read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    by_class = {
        row.corpus_search_class_id: row.value
        for row in readback.class_aggregate_metrics
        if row.ruler == "artist" and row.metric == "mrr"
    }
    assert by_class["class-t1"] != by_class["class-t2"]
    assert by_class["class-t1"] > by_class["class-t2"]
    con.close()


# ---------------------------------------------------------------------------
# C — two threshold-map rows sharing one class survive readback
# ---------------------------------------------------------------------------


def test_readback_retains_two_thresholds_sharing_one_class() -> None:
    con, _record, _result, identity = _seeded()
    readback = read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    by_index = {row.threshold_index: row for row in readback.threshold_class_map}
    assert by_index[0].corpus_search_class_id == "class-t1"
    assert by_index[1].corpus_search_class_id == "class-t1"
    assert by_index[0].corpus_search_class_id == by_index[1].corpus_search_class_id
    assert by_index[2].corpus_search_class_id == "class-t2"
    con.close()


# ---------------------------------------------------------------------------
# E — non-comparable class retains reasons and emits no partial metrics
# ---------------------------------------------------------------------------


def test_readback_retains_non_comparable_class_reasons() -> None:
    con, _record, _result, identity = _seeded()
    readback = read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    non_comparable = [row for row in readback.threshold_class_map if not row.comparable]
    assert len(non_comparable) == 1
    assert non_comparable[0].corpus_search_class_id == "class-nc"
    assert non_comparable[0].reasons == ("zero_searchable",)
    # The non-comparable class contributes no partial segmented metrics.
    assert all(row.corpus_search_class_id != "class-nc" for row in readback.class_aggregate_metrics)
    structural = {row.threshold_index: row for row in readback.threshold_structural}
    assert structural[3].comparable is False
    assert structural[3].reasons == ("zero_searchable",)
    con.close()


# ---------------------------------------------------------------------------
# L — two threshold points plus exactly one fixed baseline block
# ---------------------------------------------------------------------------


def test_readback_single_fixed_baseline_across_two_threshold_points() -> None:
    con, _record, _result, identity = _seeded()
    readback = read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    assert len(readback.threshold_class_map) == 4
    # Exactly one fixed baseline block per backbone, independent of the threshold points.
    baseline_keys = {(row.ruler, row.metric, row.k) for row in readback.baseline_aggregate_metrics}
    assert len(baseline_keys) == len(readback.baseline_aggregate_metrics)
    assert {row.backbone for row in readback.baseline_aggregate_metrics} == {_BACKBONE}
    assert len(readback.baseline_query_metrics) == 1
    assert len(readback.baseline_neighborhoods) == 1
    con.close()


# ---------------------------------------------------------------------------
# Fail-closed: missing invocation obligation / completed terminal
# ---------------------------------------------------------------------------


def test_refuses_missing_invocation_obligation() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    identity = build_geometry_corpus_identity(_rich_corpus(record))
    with pytest.raises(IntegrityRefused, match="obligation"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_missing_completed_terminal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    identity = build_geometry_corpus_identity(_rich_corpus(record))
    record_analyze_invocation(con, run_id=_RUN_ID, backbones=[(_BACKBONE, identity.geometry_id)])
    with pytest.raises(IntegrityRefused, match="terminal"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


# ---------------------------------------------------------------------------
# Fail-closed: corrupting each surface refuses instead of silently degrading
# ---------------------------------------------------------------------------


def test_refuses_duplicate_metric_rows() -> None:
    con, _record, _result, identity = _seeded()
    con.execute(
        "INSERT INTO geometry_class_aggregate_metrics (run_id, execution_id, evaluation_id,"
        " corpus_search_class_id, ruler, metric, k, value, evaluable_query_count,"
        " undefined_query_count, created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (_RUN_ID, _EXECUTION_ID, _EVALUATION_ID, "class-t1", "artist", "mrr", 10, 0.5, 1, 0, 1),
    )
    with pytest.raises(IntegrityRefused, match="duplicate class aggregate metric"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_non_finite_metric_value() -> None:
    con, _record, _result, identity = _seeded()
    con.execute(
        "UPDATE geometry_class_aggregate_metrics SET value='NaN'::DOUBLE"
        " WHERE corpus_search_class_id='class-t1' AND ruler='artist' AND metric='mrr'"
    )
    with pytest.raises(IntegrityRefused, match="finite"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_self_referential_neighborhood_row() -> None:
    con, _record, _result, identity = _seeded()
    con.execute("UPDATE geometry_class_neighborhoods SET candidate_song_id = query_song_id")
    with pytest.raises(IntegrityRefused, match="self-referential"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_duplicate_neighborhood_row() -> None:
    con, _record, _result, identity = _seeded()
    con.execute(
        "INSERT INTO geometry_class_neighborhoods (run_id, corpus_search_class_id, query_song_id,"
        " candidate_song_id, rank, score, created_at_ms) VALUES (?,?,?,?,?,?,?)",
        (_RUN_ID, "class-t1", _SONG_ID, "song-2", 1, 0.5, 1),
    )
    with pytest.raises(IntegrityRefused, match="duplicate class neighborhood"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_non_canonical_reason() -> None:
    con, _record, _result, identity = _seeded()
    con.execute("UPDATE geometry_threshold_class_map SET reasons_json='[\"bogus_reason\"]' WHERE threshold_index=0")
    with pytest.raises(IntegrityRefused, match="non-canonical reason"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_empty_required_surface() -> None:
    con, _record, _result, identity = _seeded()
    con.execute("DELETE FROM geometry_baseline_aggregate_metrics")
    with pytest.raises(IntegrityRefused, match="baseline aggregate metrics surface is empty"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_refuses_differing_identity_axis() -> None:
    con, _record, _result, identity = _seeded()
    mismatched = AnalysisEvidenceIdentity(
        geometry_id=identity.geometry_id,
        observation_group_sha256=identity.observation_group_sha256,
        geometry_semantics_version=identity.geometry_semantics_version,
        numerical_profile_digest="some-other-profile",
        threshold_id=identity.threshold_id,
        structural_identity=identity.structural_identity,
        evaluation_id=identity.evaluation_id,
        search_representation_id=identity.search_representation_id,
        scoring_semantics_version=identity.scoring_semantics_version,
        execution_id=identity.execution_id,
    )
    with pytest.raises(IntegrityRefused, match="exact scope"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=mismatched)
    con.close()


# ---------------------------------------------------------------------------
# No alternate path to the removed nested evidence shape
# ---------------------------------------------------------------------------


def test_reader_never_falls_back_to_nested_evidence_shape() -> None:
    con, _record, _result, identity = _seeded()
    for table in (
        "geometry_result_provenance",
        "geometry_evaluation_corpus",
        "geometry_threshold_class_map",
        "geometry_threshold_structural",
        "geometry_class_aggregate_metrics",
        "geometry_class_query_metrics",
        "geometry_class_neighborhoods",
        "geometry_baseline_aggregate_metrics",
        "geometry_baseline_query_metrics",
        "geometry_baseline_neighborhoods",
    ):
        con.execute(f"DELETE FROM {table}")
    # With every normalized surface gone the reader refuses; it never reconstructs the result
    # from any retired nested evidence shape.
    with pytest.raises(IntegrityRefused, match="provenance"):
        read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)
    con.close()
