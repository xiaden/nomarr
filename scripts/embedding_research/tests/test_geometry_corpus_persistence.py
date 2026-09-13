"""Focused synthetic tests for the corrective Plan D geometry corpus persistence.

They prove that one complete corpus analysis publishes atomically through the single
exact-identity DuckDB APIs (threshold-to-representation map + mandatory observed baseline +
aggregate/per-song/ruler/counter evidence + membership/missing-song/comparability evidence +
per-query ruler metrics + winner and baseline neighborhoods + invocation/terminal lifecycle),
that every geometry binding is revalidated before commit, that a non-comparable corpus is
published with explicit reasons instead of being refused, that any write failure rolls back
every output, and that the exact readers reject incomplete invocation state, duplicate rows,
non-finite values and mixed/stale evidence.  No alternate vocabulary or dual schema, real
corpus, filesystem Gram storage, or threshold-result table is involved.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    FrozenSearchRepresentation,
    GeometryAnalysisCounters,
    GeometryCorpusAnalysis,
    GeometryQueryEvidence,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    NeighborhoodEntry,
    build_geometry_corpus_identity,
    read_geometry_corpus_analysis,
    read_geometry_corpus_evidence,
    read_geometry_threshold_map,
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
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.identity_persistence import IdentityRefusal, write_analysis_rows
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


def _neighborhood(count: int, *, prefix: str = "rep") -> tuple[NeighborhoodEntry, ...]:
    return tuple(
        NeighborhoodEntry(rank, f"song-{rank + 2}", "backbone-a", f"{prefix}-{rank}", 1.0 - rank * 0.001)
        for rank in range(count)
    )


def _song_analysis(
    record,
    *,
    analysis: AllThresholdAnalysis,
    roster: GeometryRepresentationRoster,
    scores: GeometryScoreBundle,
    state: RepresentationState | None = None,
    neighborhood: tuple[NeighborhoodEntry, ...] = (),
    baseline_neighborhood: tuple[NeighborhoodEntry, ...] = (),
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
        neighborhood=neighborhood,
        baseline_neighborhood=baseline_neighborhood,
    )


def _corpus(
    record,
    *,
    comparable: bool = True,
    state: RepresentationState | None = None,
    neighborhood: tuple[NeighborhoodEntry, ...] = (),
    baseline_neighborhood: tuple[NeighborhoodEntry, ...] = (),
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
    query = _song_analysis(
        record,
        analysis=analysis,
        roster=roster,
        scores=scores,
        state=state,
        neighborhood=neighborhood,
        baseline_neighborhood=baseline_neighborhood,
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
        per_song_metrics={
            record.identity.song_id: {
                "winner_score": 0.5,
                "comparable": 1.0,
                "baseline_score": 0.25,
                "baseline_delta": 0.25,
            }
        },
        baseline_deltas={"artist": 0.25},
        comparable=comparable,
        counters=GeometryAnalysisCounters(1, 1, 1, 1, 1, 1, 0),
        queries=(query,),
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


def test_corpus_roundtrip_exact_identity_and_terminal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _corpus(record)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    state = invocation_state(con, run_id=_RUN_ID)
    assert state["obligations_present"] is True
    assert state["terminal_completed"] is True
    assert (
        con.execute(
            "SELECT count(*) FROM geometry_analysis_records "
            "WHERE run_id=? AND metric='baseline_present' AND threshold_id=?",
            (_RUN_ID, "observed-baseline:backbone-a"),
        ).fetchone()[0]
        > 0
    )

    identity = build_geometry_corpus_identity(result)
    loaded = read_geometry_corpus_analysis(con, run_id=_RUN_ID, identity=identity)
    assert loaded.run_id == _RUN_ID
    assert loaded.execution_id == _EXECUTION_ID
    assert loaded.experiment == "temporal_global"
    assert loaded.comparable is True
    assert loaded.artist_metrics["mean_winner"] == pytest.approx(0.5)
    assert loaded.per_song_metrics[record.identity.song_id]["baseline_delta"] == pytest.approx(0.25)
    assert loaded.baseline_deltas["artist"] == pytest.approx(0.25)
    assert loaded.counters == GeometryAnalysisCounters(1, 1, 1, 1, 1, 1, 0)

    wrong = AnalysisEvidenceIdentity(
        geometry_id="superseded",
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
    with pytest.raises(IdentityRefusal):
        read_geometry_corpus_analysis(con, run_id=_RUN_ID, identity=wrong)
    con.close()


def test_threshold_map_and_corpus_evidence_roundtrip() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _corpus(record, neighborhood=_neighborhood(100), baseline_neighborhood=_neighborhood(100, prefix="base"))
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    identity = build_geometry_corpus_identity(result)
    threshold_map = read_geometry_threshold_map(con, run_id=_RUN_ID, identity=identity)
    assert len(threshold_map) == 1
    assert threshold_map[0].threshold_id == "temporal_global:threshold:0:0.0"
    assert threshold_map[0].structural_identity == "structural-a"
    assert threshold_map[0].search_representation_id == "representation-a"
    assert threshold_map[0].song_id == record.identity.song_id
    assert threshold_map[0].comparable is True

    evidence = read_geometry_corpus_evidence(con, run_id=_RUN_ID, identity=identity)
    assert evidence.comparable is True
    assert len(evidence.membership) == 1
    assert evidence.membership[0].observation_group_sha256 == record.identity.observation_group_sha256
    assert evidence.missing_searchable == ()
    assert len(evidence.queries) == 1
    query = evidence.queries[0]
    assert isinstance(query, GeometryQueryEvidence)
    assert query.winner_score == pytest.approx(0.5)
    assert query.baseline_score == pytest.approx(0.25)
    assert query.baseline_delta == pytest.approx(0.25)
    assert query.searchable_count == 3
    assert [entry.rank for entry in query.neighborhood] == list(range(100))
    assert len(query.neighborhood) == 100
    assert len(query.baseline_neighborhood) == 100
    assert query.neighborhood[0].search_representation_id == "rep-0"
    assert query.baseline_neighborhood[0].search_representation_id == "base-0"
    con.close()


def test_non_comparable_corpus_publishes_explicit_reasons() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    state = RepresentationState(False, False, False, ("no_searchable",))
    result = _corpus(record, comparable=False, state=state)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    assert invocation_state(con, run_id=_RUN_ID)["terminal_completed"] is True
    identity = build_geometry_corpus_identity(result)
    loaded = read_geometry_corpus_analysis(con, run_id=_RUN_ID, identity=identity)
    assert loaded.comparable is False
    assert "no_searchable" in loaded.reasons

    evidence = read_geometry_corpus_evidence(con, run_id=_RUN_ID, identity=identity)
    assert evidence.comparable is False
    assert "no_searchable" in evidence.reasons
    assert evidence.queries[0].comparable is False
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
            if isinstance(sql, str) and "geometry_analysis_records" in sql:
                raise RuntimeError("injected corpus write failure")
            return con.execute(sql, params) if params is not None else con.execute(sql)

        def executemany(self, sql, params):
            if isinstance(sql, str) and "geometry_analysis_records" in sql:
                raise RuntimeError("injected corpus write failure")
            return con.executemany(sql, params)

        def cursor(self):
            return con.cursor()

    with pytest.raises(RuntimeError, match="injected corpus write failure"):
        write_geometry_corpus_analysis(_FailingConnection(), run_id=_RUN_ID, result=_corpus(record))

    assert con.execute("SELECT count(*) FROM geometry_analysis_records").fetchone()[0] == 0
    assert invocation_state(con, run_id=_RUN_ID)["obligations_present"] is False
    con.close()


def test_reader_rejects_incomplete_invocation_state() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    identity = _raw_identity(record)
    record_analyze_invocation(con, run_id="run-open", backbones=[])
    write_analysis_rows(
        con,
        run_id="run-open",
        identity=identity,
        metrics={"corpus_present": 1.0},
        evidence={"role": "corpus"},
    )
    with pytest.raises(ValueError, match="invocation state is incomplete"):
        read_geometry_corpus_analysis(con, run_id="run-open", identity=identity)
    con.close()


def test_reader_rejects_duplicate_and_nonfinite_rows() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    result = _corpus(record)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)
    identity = build_geometry_corpus_identity(result)
    evidence = con.execute(
        "SELECT evidence_json FROM geometry_analysis_records WHERE run_id=? AND threshold_id='corpus' LIMIT 1",
        (_RUN_ID,),
    ).fetchone()[0]

    columns = (
        "run_id, geometry_id, observation_group_sha256, geometry_semantics_version, numerical_profile_digest,"
        " threshold_id, structural_identity, search_representation_id, evaluation_id,"
        " scoring_semantics_version, execution_id, metric, value, evidence_json, created_at_ms"
    )
    base = (
        _RUN_ID,
        identity.geometry_id,
        identity.observation_group_sha256,
        identity.geometry_semantics_version,
        identity.numerical_profile_digest,
        "corpus",
        "temporal_global:corpus",
        "corpus",
        _EVALUATION_ID,
        1,
        _EXECUTION_ID,
    )
    con.execute(
        f"INSERT INTO geometry_analysis_records ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [*base, "artist_active", 1.0, evidence, 1],
    )
    with pytest.raises(ValueError, match="duplicate geometry corpus evidence rows"):
        read_geometry_corpus_analysis(con, run_id=_RUN_ID, identity=identity)
    con.execute("DELETE FROM geometry_analysis_records WHERE metric='artist_active'")
    con.execute(
        f"INSERT INTO geometry_analysis_records ({columns}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [*base, "nonfinite_probe", float("nan"), evidence, 1],
    )
    with pytest.raises(ValueError, match="non-finite geometry evidence"):
        read_geometry_corpus_analysis(con, run_id=_RUN_ID, identity=identity)
    con.close()


def test_writer_rejects_mismatched_run_and_missing_baseline() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    record = _seed_geometry(con)
    with pytest.raises(ValueError, match="run identity does not match"):
        write_geometry_corpus_analysis(con, run_id="run-other", result=_corpus(record))
    assert con.execute("SELECT count(*) FROM geometry_analysis_records").fetchone()[0] == 0
    con.close()
