"""Focused synthetic tests for the real geometry corpus owner (Plan K P2-S9)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    GeometryCorpusRequest,
    GeometrySongRequest,
    IntegrityRefused,
    analyze_geometry_corpus,
    build_geometry_corpus_request,
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
    assert not any(row.comparable for row in result.threshold_class_map)
    con.close()


def test_owner_zero_mask_is_refused_not_dropped() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, request = _seed(con)
    observation.mask = np.zeros(3, dtype=np.uint8)
    store = _Store(observation)
    with pytest.raises(IntegrityRefused) as excinfo:
        analyze_geometry_corpus(
            request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
        )
    # The fixed evaluation corpus refuses a song with zero whole-song searchable mass; it is
    # never dropped, and no shrunken/non-comparable corpus is ever emitted.
    assert "INTEGRITY_REFUSED" in str(excinfo.value)
    assert "zero_searchable" in str(excinfo.value)
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


def test_builder_to_analyze_empirical_handoff_requires_frozen_current_head(monkeypatch) -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, _request = _seed(con)
    store = _Store(observation)
    profile = GeometryProfile.current()
    song = {"song_id": "song-1", "artist": "artist-a", "genre": "genre-a"}
    monkeypatch.setattr(
        "scripts.embedding_research.common.geometry_analysis._selected_geometry_items",
        lambda *_args: ((song, "backbone-a"),),
    )
    from scripts.embedding_research.common.head_ruler_labels import HeadSongLabel

    label = HeadSongLabel(
        song_id="song-1",
        backbone="backbone-a",
        full_tuple=(("gender", 1), ("timbre", 0)),
        labels=("male", "bright"),
        pooled=(0.8, 0.2),
        searchable_rows=3,
        head_set_fingerprint="head-suite-current",
        head_ids="gender,timbre",
        dim_by_head="gender:2,timbre:2",
        stream_ref="stream-ref",
        stream_digest="stream-digest",
        mask_ref="mask-ref",
        mask_digest="mask-digest",
        present=True,
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.geometry_analysis.resolve_head_ruler_labels",
        lambda **_kwargs: label,
    )
    request = build_geometry_corpus_request(
        con,
        stream_store=store,
        profile=profile,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-empirical",
        run_id="run-empirical",
        execution_id="execution-empirical",
        scoring_semantics_version=1,
        head_store=SimpleNamespace(output_root=Path("/synthetic/current-heads")),
        synthetic_only=False,
    )
    result = analyze_geometry_corpus(request, con=con, stream_store=store, profile=profile)
    assert result.synthetic_only is False
    assert result.evidence_mode == "empirical_request"
    assert result.head_evidence_provenance == {
        "head_suite_identities": ["head-suite-current"],
        "head_labels_bound": 1,
        "current_head_bindings": [
            {"song_id": "song-1", "backbone": "backbone-a", "head_suite_identity": "head-suite-current"}
        ],
        "source": "current_committed_head_suite",
    }
    assert len(result.analyses) == 1 and len(result.analyses[0].results) == 171
    assert result.hypotheses and result.queries

    # A missing per-song head label must NOT refuse the request: it excludes the song from
    # the HEAD ruler only and never fabricates an ``unknown`` label.
    missing = replace(
        request.items[0],
        head_label=None,
        head_suite_identity=None,
        head_provenance=None,
    )
    accepted = replace(request, items=(missing,))
    result2 = analyze_geometry_corpus(accepted, con=con, stream_store=store, profile=profile)
    assert result2.head_evidence_provenance["head_labels_bound"] == 0
    assert result2.head_evidence_provenance["current_head_bindings"] == []
    con.close()


def test_supersession_refuses_before_result_publication() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observation, _record, request = _seed(con)
    original = observation.identity.observation_group_sha256
    observation.identity.observation_group_sha256 = "commit-superseded"
    with pytest.raises(StaleRefused, match="requested geometry identity"):
        analyze_geometry_corpus(
            request, con=con, stream_store=_Store(observation), profile=GeometryProfile.current(), scoring=_scorer([])
        )
    assert observation.identity.observation_group_sha256 != original
    con.close()
