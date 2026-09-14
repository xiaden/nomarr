"""Focused synthetic tests for normalized geometry corpus persistence.

They prove that one complete corpus analysis publishes atomically through the seven
normalized result surfaces + one compact provenance row + the invocation/terminal
lifecycle, that a non-comparable corpus is published with explicit reasons instead of
being refused, that any write failure rolls back every output, and that the normalized
reader rejects incomplete invocation state and refuses a pre-cut database.  No alternate
vocabulary or dual schema, real corpus, filesystem Gram storage, or nested evidence table
is involved.
"""

from __future__ import annotations

from dataclasses import replace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    GeometryAnalysisCounters,
    GeometryBaselineAggregateMetric,
    GeometryCandidate,
    GeometryCorpusAnalysis,
    GeometryCorpusHypothesis,
    GeometryEvaluationCorpusEntry,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    GeometryThresholdClassRow,
    GeometryThresholdStructuralRow,
    RankedNeighbor,
    build_geometry_corpus_identity,
    corpus_result_identity_from_provenance,
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
from scripts.embedding_research.db.analyze_scope import invocation_state, record_analyze_invocation
from scripts.embedding_research.db.geometry import GeometryIdentity, IntegrityRefused
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.result_surfaces import read_result_provenance
from scripts.embedding_research.helpers.corpus_identity import RepresentationState

pytestmark = pytest.mark.unit

_RUN_ID = "run-a"
_EXECUTION_ID = "execution-a"
_EVALUATION_ID = "evaluation-a"


class _Identity:
    song_id = "song-1"
    backbone = "backbone-a"
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


def _song_analysis(
    record,
    *,
    analysis: AllThresholdAnalysis,
    roster: GeometryRepresentationRoster,
    scores: GeometryScoreBundle,
    state: RepresentationState | None = None,
) -> GeometrySongAnalysis:
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
    return GeometrySongAnalysis(
        request=request,
        thresholds=analysis,
        roster=roster,
        scores=scores,
        state=state or RepresentationState(True, True, True, ()),
        neighborhood=(RankedNeighbor(0, "song-2", "backbone-a", "rep-0", 0.9),),
        baseline_neighborhood=(RankedNeighbor(0, "song-2", "backbone-a", "observed-medoid-0", 0.4),),
        threshold_id=analysis.results[0].threshold.threshold_id,
        collapse_class_id="collapse:representation-a",
    )


def _corpus(
    record,
    *,
    comparable: bool = True,
    state: RepresentationState | None = None,
) -> GeometryCorpusAnalysis:
    threshold = ThresholdSpec(0, 0.0, "temporal_global:threshold:0:0.0")
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
        evaluation_comparable=comparable,
    )
    query = _song_analysis(record, analysis=analysis, roster=roster, scores=scores, state=state)
    hypothesis = GeometryCorpusHypothesis(
        threshold_id=threshold.threshold_id,
        collapse_class_id="collapse:representation-a",
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
        comparable=comparable,
        counters=GeometryAnalysisCounters(1, 1, 1, 1, 1, 1, 0),
        # A threshold-independent baseline aggregate makes the backbone obligation resolve so the
        # run terminalizes exactly once.
        baseline_aggregate_metrics=(GeometryBaselineAggregateMetric("backbone-a", "artist", "mrr", 10, 0.25, 1, 0),),
        reasons=() if comparable else ("zero_searchable",),
        queries=(query,),
        hypotheses=(hypothesis,),
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
        threshold_class_map=(
            GeometryThresholdClassRow(
                threshold_index=threshold.index,
                threshold_id=threshold.threshold_id,
                threshold_value=float(threshold.value),
                corpus_search_class_id="representation-a",
                comparable=comparable,
                reasons=(),
            ),
        ),
        threshold_structural=(
            GeometryThresholdStructuralRow(
                song_id=record.identity.song_id,
                backbone=record.identity.backbone,
                threshold_index=threshold.index,
                threshold_id=threshold.threshold_id,
                structural_identity=structural.identity,
                search_representation_id="representation-a",
                searchable_count=3,
                medoid_defined=True,
                alignment_ok=True,
                comparable=comparable,
                reasons=(),
            ),
        ),
    )


def _raw_identity(record) -> AnalysisEvidenceIdentity:
    return AnalysisEvidenceIdentity(
        geometry_id=record.geometry_id,
        observation_group_sha256=record.identity.observation_group_sha256,
        geometry_semantics_version=record.identity.geometry_semantics_version,
        numerical_profile_digest=record.identity.numerical_profile_digest,
        threshold_id="corpus",
        structural_identity="temporal_global:corpus",
        evaluation_id=_EVALUATION_ID,
        search_representation_id="corpus",
        scoring_semantics_version=1,
        execution_id=_EXECUTION_ID,
    )


def _read_normalized(con, _record):
    provenance = read_result_provenance(con, run_id=_RUN_ID)
    assert len(provenance) == 1
    identity = corpus_result_identity_from_provenance(provenance[0])
    return read_geometry_corpus_analysis_normalized(con, run_id=_RUN_ID, identity=identity)


def test_corpus_roundtrip_normalized_and_terminal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _corpus(record)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    state = invocation_state(con, run_id=_RUN_ID)
    assert state["obligations_present"] is True
    assert state["terminal_completed"] is True
    assert (
        con.execute("SELECT count(*) FROM geometry_baseline_aggregate_metrics WHERE run_id=?", (_RUN_ID,)).fetchone()[0]
        > 0
    )

    # The corpus identity is still derivable from the result for identity assertions.
    assert build_geometry_corpus_identity(result).evaluation_id == _EVALUATION_ID

    loaded = _read_normalized(con, record)
    assert loaded.run_id == _RUN_ID
    assert loaded.provenance.execution_id == _EXECUTION_ID
    assert loaded.provenance.experiment == "temporal_global"
    assert loaded.provenance.comparable is True
    assert len(loaded.evaluation_corpus) == 1
    assert len(loaded.threshold_class_map) == 1
    assert len(loaded.baseline_aggregate_metrics) == 1
    con.close()


def test_non_comparable_corpus_publishes_explicit_reasons() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    state = RepresentationState(False, False, False, ("zero_searchable",))
    result = _corpus(record, comparable=False, state=state)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    assert invocation_state(con, run_id=_RUN_ID)["terminal_completed"] is True
    loaded = _read_normalized(con, record)
    assert loaded.provenance.comparable is False
    assert "zero_searchable" in loaded.provenance.reasons
    con.close()


def test_corpus_duplicate_publication_is_refused() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _corpus(record)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)
    with pytest.raises(ValueError, match="already terminalized"):
        write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)
    con.close()


def test_corpus_rolls_back_on_injected_write_failure() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)

    class _FailingConnection:
        def execute(self, sql, params=None):
            if isinstance(sql, str) and "geometry_baseline_aggregate_metrics" in sql:
                raise RuntimeError("injected corpus write failure")
            return con.execute(sql, params) if params is not None else con.execute(sql)

        def executemany(self, sql, params):
            if isinstance(sql, str) and "geometry_baseline_aggregate_metrics" in sql:
                raise RuntimeError("injected corpus write failure")
            return con.executemany(sql, params)

        def cursor(self):
            return con.cursor()

    with pytest.raises(RuntimeError, match="injected corpus write failure"):
        write_geometry_corpus_analysis(_FailingConnection(), run_id=_RUN_ID, result=_corpus(record))

    assert con.execute("SELECT count(*) FROM geometry_baseline_aggregate_metrics").fetchone()[0] == 0
    assert invocation_state(con, run_id=_RUN_ID)["obligations_present"] is False
    con.close()


def test_reader_rejects_incomplete_invocation_state() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    identity = _raw_identity(record)
    record_analyze_invocation(con, run_id="run-open", backbones=[])
    with pytest.raises(IntegrityRefused, match="terminal record is missing"):
        read_geometry_corpus_analysis_normalized(con, run_id="run-open", identity=identity)
    con.close()


def test_empirical_publication_persists_head_provenance() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    empirical = replace(
        _corpus(record),
        synthetic_only=False,
        evidence_mode="empirical_request",
        head_evidence_provenance={
            "source": "current_committed_head_suite",
            "head_suite_identities": ["head-set-a"],
            "head_labels_bound": 1,
        },
    )
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=empirical)
    provenance = read_result_provenance(con, run_id=_RUN_ID)[0]
    assert provenance["evidence_mode"] == "empirical_request"
    assert provenance["head_evidence_provenance"]["head_suite_identities"] == ["head-set-a"]
    con.close()


def test_empirical_publication_refuses_missing_head_provenance_atomically() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    empirical = replace(_corpus(record), synthetic_only=False, evidence_mode="empirical_request")
    with pytest.raises(IntegrityRefused, match="frozen-head provenance"):
        write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=empirical)
    assert con.execute("SELECT count(*) FROM geometry_baseline_aggregate_metrics").fetchone()[0] == 0
    assert invocation_state(con, run_id=_RUN_ID)["obligations_present"] is False
    con.close()


def test_writer_rejects_mismatched_run_and_missing_baseline() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    with pytest.raises(ValueError, match="run identity does not match"):
        write_geometry_corpus_analysis(con, run_id="run-other", result=_corpus(record))
    assert con.execute("SELECT count(*) FROM geometry_baseline_aggregate_metrics").fetchone()[0] == 0
    con.close()
