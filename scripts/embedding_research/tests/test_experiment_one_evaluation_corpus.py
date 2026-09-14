"""Plan A Phase 1: the ONE fixed evaluation corpus and its single persistence.

These spec-first tests pin the corrective Experiment One contract: the evaluation corpus is
resolved once per analyze invocation, before any threshold evaluation, and its membership is
decided only by the whole-song observed-global-medoid baseline representation (finite nonzero
observed medoid row plus a valid committed binary mask).  Artist, genre, and head labels never
participate; a zero-searchable song is refused rather than dropped; a multi-backbone corpus is
refused; and the persisted membership is O(N) and identical when the configured threshold count
changes from 2 to 171.  No compatibility shim, dual schema, or threshold-copied membership is
involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common import geometry_analysis
from scripts.embedding_research.common.geometry_analysis import (
    GeometryCorpusRequest,
    GeometrySongRequest,
    analyze_geometry_corpus,
    resolve_geometry_evaluation_corpus,
)
from scripts.embedding_research.common.threshold_analysis import (
    SecondaryChebyshevRequest,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry import GeometryIdentity, IntegrityRefused
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.identity_persistence import (
    IdentityRefusal,
    read_evaluation_corpus,
    write_evaluation_corpus,
)

pytestmark = pytest.mark.unit

_STREAM = np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32)


class _Identity:
    mask_ref = "mask-ref"
    mask_digest = "mask-a"
    alignment_token = "align"
    audio_content_sha256 = "audio-digest"
    mask_semantics_version = "mask-v1"
    group_format_version = "group-v1"

    def __init__(self, song_id: str, backbone: str) -> None:
        self.song_id = song_id
        self.backbone = backbone
        self.patch_count = 3
        self.commit_sha256 = f"commit:{song_id}:{backbone}"
        self.observation_group_sha256 = f"commit:{song_id}:{backbone}"


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
    def __init__(self, con, song_id: str, backbone: str, mask: np.ndarray | None = None) -> None:
        self.con = con
        self.identity = _Identity(song_id, backbone)
        self.stream_record = _StreamRecord()
        self.stream = _STREAM
        self.mask = np.ones(3, dtype=np.uint8) if mask is None else mask
        self.provenance_identity = "provenance"


class _Store:
    """Serves the already-committed observations for every ``(song_id, backbone)``."""

    def __init__(self, observations: dict[tuple[str, str], _Observation]) -> None:
        self.observations = observations
        self.loads = 0

    def load_committed_observation(self, song_id: str, backbone: str) -> _Observation:
        self.loads += 1
        return self.observations[(song_id, backbone)]

    def batch_gather(self, song_id: str, backbone: str, indices, *, forbid_duplicates: bool):
        assert forbid_duplicates is True
        return np.asarray(self.observations[(song_id, backbone)].stream[list(indices)], dtype=np.float32)


def _scorer():
    def score(_query, _weights, _candidate):
        return SimpleNamespace(finite=True, score=0.5)

    return score


def _seed_songs(con, specs):
    """Write geometry for each ``(song_id, backbone, mask)`` spec and return request items."""
    observations: dict[tuple[str, str], _Observation] = {}
    items: list[GeometrySongRequest] = []
    profile = GeometryProfile.current()
    for song_id, backbone, mask, head_label in specs:
        observation = _Observation(con, song_id, backbone, mask)
        record = write_geometry(observation, profile, "seed-run")
        observations[(song_id, backbone)] = observation
        identity = GeometryIdentity(
            song_id,
            backbone,
            observation.identity.observation_group_sha256,
            record.identity.geometry_semantics_version,
            record.identity.numerical_profile_digest,
        )
        items.append(
            GeometrySongRequest(
                song_id,
                backbone,
                identity,
                dict(record.evidence),
                artist="artist-a",
                genre="genre-a",
                head_label=head_label,
            )
        )
    items.sort(key=lambda item: (item.song_id, item.backbone))
    return observations, tuple(items)


def _request(items, *, threshold_request, experiment, evaluation_id, execution_id, run_id="run-a"):
    return GeometryCorpusRequest(
        items=items,
        threshold_request=threshold_request,
        experiment=experiment,
        evaluation_id=evaluation_id,
        scoring_semantics_version=1,
        run_id=run_id,
        execution_id=execution_id,
        numerical_profile_digest=GeometryProfile.current().digest,
    )


def test_membership_is_independent_of_artist_genre_and_head_labels() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, items = _seed_songs(
        con,
        [
            ("song-1", "backbone-a", None, None),  # missing head label
            ("song-2", "backbone-a", None, ("head-a",)),
        ],
    )
    request = _request(
        items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        execution_id="execution:run-a:backbone-a",
    )
    result = analyze_geometry_corpus(
        request, con=con, stream_store=_Store(observations), profile=GeometryProfile.current(), scoring=_scorer()
    )

    # A missing head label must NOT remove the song from the fixed evaluation corpus.
    members = {(entry.song_id, entry.backbone) for entry in result.evaluation_corpus}
    assert members == {("song-1", "backbone-a"), ("song-2", "backbone-a")}
    assert all(entry.baseline_valid and entry.comparable for entry in result.evaluation_corpus)
    con.close()


def test_resolver_is_called_exactly_once_and_never_per_threshold(monkeypatch) -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, items = _seed_songs(
        con,
        [
            ("song-1", "backbone-a", None, ("head-a",)),
            ("song-2", "backbone-a", None, ("head-a",)),
        ],
    )
    request = _request(
        items,
        threshold_request=dense_primary_threshold_request(),  # 171 configured thresholds
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        execution_id="execution:run-a:backbone-a",
    )
    calls = {"count": 0}
    original = geometry_analysis.resolve_geometry_evaluation_corpus

    def counting(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(geometry_analysis, "resolve_geometry_evaluation_corpus", counting)
    result = analyze_geometry_corpus(
        request, con=con, stream_store=_Store(observations), profile=GeometryProfile.current(), scoring=_scorer()
    )

    assert calls["count"] == 1
    assert len(request.threshold_request.indices) == 171
    assert len(result.evaluation_corpus) == 2
    con.close()


def test_zero_searchable_song_is_refused_not_dropped() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, items = _seed_songs(
        con,
        [
            ("song-1", "backbone-a", np.zeros(3, dtype=np.uint8), ("head-a",)),
            ("song-2", "backbone-a", None, ("head-a",)),
        ],
    )
    request = _request(
        items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        execution_id="execution:run-a:backbone-a",
    )
    with pytest.raises(IntegrityRefused) as excinfo:
        analyze_geometry_corpus(
            request, con=con, stream_store=_Store(observations), profile=GeometryProfile.current(), scoring=_scorer()
        )
    assert "INTEGRITY_REFUSED" in str(excinfo.value)
    assert "zero_searchable" in str(excinfo.value)
    con.close()


def test_multi_backbone_corpus_is_refused() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, items = _seed_songs(
        con,
        [
            ("song-1", "backbone-a", None, ("head-a",)),
            ("song-1", "backbone-b", None, ("head-a",)),
        ],
    )
    request = _request(
        items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        execution_id="execution:run-a:mixed",
    )
    with pytest.raises(IntegrityRefused) as excinfo:
        analyze_geometry_corpus(
            request, con=con, stream_store=_Store(observations), profile=GeometryProfile.current(), scoring=_scorer()
        )
    assert "INTEGRITY_REFUSED" in str(excinfo.value)
    assert "multiple backbones" in str(excinfo.value)
    con.close()


def test_single_backbone_execution_carries_backbone_scoped_execution_id() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations, items = _seed_songs(con, [("song-1", "backbone-a", None, ("head-a",))])
    request = _request(
        items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        execution_id="execution:run-a:backbone-a",
    )
    result = analyze_geometry_corpus(
        request, con=con, stream_store=_Store(observations), profile=GeometryProfile.current(), scoring=_scorer()
    )

    assert result.execution_id == "execution:run-a:backbone-a"
    assert {entry.backbone for entry in result.evaluation_corpus} == {"backbone-a"}
    con.close()


def test_persisted_membership_is_one_row_per_identity_and_threshold_independent() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _, items = _seed_songs(
        con,
        [
            ("song-1", "backbone-a", None, ("head-a",)),
            ("song-2", "backbone-a", None, None),  # label independence again
        ],
    )

    def resolve(item):
        # Reuse the already-written geometry matrices; only membership matters here.
        from scripts.embedding_research.common.geometry_analysis import require_exact_binary_mask
        from scripts.embedding_research.db.geometry import read_geometry

        record = read_geometry(item.geometry_identity, con)
        mask = require_exact_binary_mask(np.ones(3, dtype=np.uint8), record.matrix.shape[0])
        return record, mask

    two = _request(
        items,
        threshold_request=SecondaryChebyshevRequest((1.0, 2.0)),
        experiment=SecondaryChebyshevRequest((1.0, 2.0)).experiment,
        evaluation_id="evaluation-2",
        execution_id="execution:run-a:backbone-a",
    )
    many = _request(
        items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-171",
        execution_id="execution:run-a:backbone-a",
    )

    entries_two = resolve_geometry_evaluation_corpus(two.items, resolve_record_mask=resolve)
    entries_many = resolve_geometry_evaluation_corpus(many.items, resolve_record_mask=resolve)
    assert len(entries_two) == len(entries_many) == 2
    assert two.items == many.items

    write_evaluation_corpus(
        con,
        run_id="run-a",
        evaluation_id="evaluation-2",
        experiment=two.experiment,
        execution_id="execution:run-a:backbone-a",
        entries=entries_two,
    )
    write_evaluation_corpus(
        con,
        run_id="run-a",
        evaluation_id="evaluation-171",
        experiment="temporal_global",
        execution_id="execution:run-a:backbone-a",
        entries=entries_many,
    )

    total = con.execute("SELECT count(*) FROM geometry_evaluation_corpus WHERE run_id='run-a'").fetchone()[0]
    assert total == 4  # N=2 songs, once per evaluation, never per threshold
    distinct = con.execute(
        "SELECT count(*) FROM (SELECT DISTINCT run_id, evaluation_id, song_id, backbone "
        "FROM geometry_evaluation_corpus WHERE run_id='run-a')"
    ).fetchone()[0]
    assert distinct == total

    stored = read_evaluation_corpus(con, run_id="run-a", evaluation_id="evaluation-171")
    assert {row["song_id"] for row in stored} == {"song-1", "song-2"}
    assert all(row["baseline_valid"] and row["comparable"] for row in stored)
    assert all(row["created_at_ms"] > 0 for row in stored)

    # Writing the same identity again is refused (application-enforced one-row identity).
    with pytest.raises(IdentityRefusal):
        write_evaluation_corpus(
            con,
            run_id="run-a",
            evaluation_id="evaluation-171",
            experiment="temporal_global",
            execution_id="execution:run-a:backbone-a",
            entries=entries_many,
        )
    con.close()
