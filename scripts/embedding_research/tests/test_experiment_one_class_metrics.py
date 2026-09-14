"""Focused synthetic tests for Experiment One class-scoped metrics (Plan A Phase 4).

These tests prove the class-scoped result semantics required by the hard cut:

* **B** — two threshold classes with opposite rankings (same-artist first vs a
  non-artist first) produce different metrics.
* **C** — identical complete scoring inputs collapse to one class with one metric
  block and one neighborhood set; at the owner level, equal thresholds are never
  multiplied into duplicate per-threshold retrieval rows.
* **D** — mutating one song's representation prevents that collapse.
* **F** — a same-artist *baseline* candidate with an unrelated representation id is
  still relevant by song identity.
* **H** — the retained top-100 neighborhood is a browsing window only; MRR uses the
  complete ranking, so a first relevant hit beyond rank 100 contributes ``1/rank``.

No real corpus, model, audio, ONNX, or CUDA is involved.
"""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    _NEIGHBORHOOD_SIZE,
    FrozenSearchRepresentation,
    GeometryCorpusRequest,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    _geometry_class_scoped_metrics,
    _select_neighborhood,
    analyze_geometry_corpus,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RUN_ID = "run-class-metrics"
_EVALUATION_ID = "evaluation-class-metrics"
_EXECUTION_ID = "execution:run-class-metrics:effnet"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _request(
    song_id: str,
    *,
    artist: object | None = None,
    genre: object | None = None,
    head_label: object | None = None,
) -> GeometrySongRequest:
    return GeometrySongRequest(
        song_id=song_id,
        backbone=_BACKBONE,
        geometry_identity=GeometryIdentity(song_id, _BACKBONE, f"commit:{song_id}", "geometry-v1", "profile-a"),
        observation_evidence={"observation_group_sha256": f"obs:{song_id}"},
        artist=artist,  # type: ignore[arg-type]
        genre=genre,  # type: ignore[arg-type]
        head_label=head_label,
    )


def _thresholds(song_id: str) -> AllThresholdAnalysis:
    return AllThresholdAnalysis(
        experiment="temporal_global",
        geometry_id=f"geometry:{song_id}",
        observation_group_sha256=f"obs:{song_id}",
        profile_digest="profile-a",
        mask_digest="mask-a",
        results=(),
        geometry_semantics_version="geometry-v1",
        evaluation_id=_EVALUATION_ID,
        execution_id=_EXECUTION_ID,
    )


def _representation(
    song_id: str, *, rid: str | None = None, vectors: object | None = None
) -> FrozenSearchRepresentation:
    return FrozenSearchRepresentation(
        song_id=song_id,
        backbone=_BACKBONE,
        source_indices=(0,),
        vectors=np.asarray([[1.0, 0.0]] if vectors is None else vectors, dtype=np.float32),
        weights=np.ones(1, dtype=np.float64),
        search_representation_id=rid or f"rep:{song_id}",
        geometry_id=f"geometry:{song_id}",
        observation_group_sha256=f"obs:{song_id}",
        numerical_profile_digest="profile-a",
        mask_digest="mask-a",
        scoring_semantics_version=1,
        experiment="temporal_global",
    )


def _analysis(
    song_id: str,
    candidate_scores: dict[str, float],
    *,
    artist: object | None = None,
    genre: object | None = None,
    head_label: object | None = None,
) -> GeometrySongAnalysis:
    representations = tuple(_representation(candidate) for candidate in candidate_scores)
    roster = GeometryRepresentationRoster(representations)
    scores = {
        representation.search_representation_id: float(value)
        for representation, value in zip(representations, candidate_scores.values(), strict=True)
    }
    lookup = {representation.search_representation_id: representation for representation in representations}
    return GeometrySongAnalysis(
        _request(song_id, artist=artist, genre=genre, head_label=head_label),
        _thresholds(song_id),
        roster,
        GeometryScoreBundle(scores=scores, evaluation_comparable=True),
        neighborhood=_select_neighborhood(scores, lookup),
    )


def _run_helper(
    songs: list[dict[str, object]],
    classes: dict[str, dict[str, dict[str, float]]],
    baseline_vectors: dict[str, object],
):
    items = tuple(
        sorted(
            (
                _request(
                    str(song["song_id"]),
                    artist=song.get("artist"),
                    genre=song.get("genre"),
                    head_label=song.get("head_label"),
                )
                for song in songs
            ),
            key=lambda item: (item.song_id, item.backbone),
        )
    )
    request = GeometryCorpusRequest(
        items=items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id=_EVALUATION_ID,
        scoring_semantics_version=1,
        run_id=_RUN_ID,
        execution_id=_EXECUTION_ID,
        numerical_profile_digest="profile-a",
    )
    label_by_song = {str(song["song_id"]): song for song in songs}
    scored: dict[tuple[str, str], GeometrySongAnalysis] = {}
    for class_id, by_query in classes.items():
        for query_song, candidate_scores in by_query.items():
            labels = label_by_song[query_song]
            scored[(class_id, query_song)] = _analysis(
                query_song,
                candidate_scores,
                artist=labels.get("artist"),
                genre=labels.get("genre"),
                head_label=labels.get("head_label"),
            )
    baseline_roster = {
        (str(song["song_id"]), _BACKBONE): _representation(
            str(song["song_id"]),
            rid=f"base:{song['song_id']}",
            vectors=baseline_vectors[str(song["song_id"])],
        )
        for song in songs
    }
    return _geometry_class_scoped_metrics(
        request=request,
        scored_queries=scored,
        baseline_roster=baseline_roster,
    )


def _aggregate(rows, class_id: str, ruler: str) -> dict[str, float]:
    return {row.metric: row.value for row in rows if row.corpus_search_class_id == class_id and row.ruler == ruler}


def _neighborhood(rows, class_id: str, query_song: str) -> list[tuple[int, str]]:
    selected = [row for row in rows if row.corpus_search_class_id == class_id and row.query_song_id == query_song]
    return [(row.rank, row.candidate_song_id) for row in sorted(selected, key=lambda row: row.rank)]


# ---------------------------------------------------------------------------
# B — threshold classes with opposite rankings diverge
# ---------------------------------------------------------------------------


def test_b_artist_first_and_non_artist_first_classes_diverge() -> None:
    songs = [
        {"song_id": "song-q", "artist": "art-a"},
        {"song_id": "song-a", "artist": "art-a"},
        {"song_id": "song-b", "artist": "art-b"},
    ]
    classes = {
        "class-t1": {
            "song-q": {"song-a": 0.9, "song-b": 0.1},
            "song-a": {"song-q": 0.9, "song-b": 0.1},
            "song-b": {"song-q": 0.1, "song-a": 0.1},
        },
        "class-t2": {
            "song-q": {"song-a": 0.1, "song-b": 0.9},
            "song-a": {"song-q": 0.1, "song-b": 0.9},
            "song-b": {"song-q": 0.9, "song-a": 0.1},
        },
    }
    baseline = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}
    class_aggregate, _query, class_neighborhood, _ba, _bq, _bn = _run_helper(songs, classes, baseline)

    t1 = _aggregate(class_aggregate, "class-t1", "artist")
    t2 = _aggregate(class_aggregate, "class-t2", "artist")

    # T1 ranks the same-artist candidate first; T2 ranks the non-artist candidate first.
    assert _neighborhood(class_neighborhood, "class-t1", "song-q")[0][1] == "song-a"
    assert _neighborhood(class_neighborhood, "class-t2", "song-q")[0][1] == "song-b"
    assert t1["mrr"] == pytest.approx(1.0)
    assert t2["mrr"] == pytest.approx(0.5)
    assert t1["mrr"] != t2["mrr"]
    assert t1["map_k"] != t2["map_k"]


# ---------------------------------------------------------------------------
# C — identical scoring inputs collapse; owner never multiplies per threshold
# ---------------------------------------------------------------------------


def test_c_identical_class_inputs_collapse_to_identical_metrics_and_neighborhoods() -> None:
    songs = [
        {"song_id": "song-q", "artist": "art-a"},
        {"song_id": "song-a", "artist": "art-a"},
        {"song_id": "song-b", "artist": "art-b"},
    ]
    identical = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }
    classes = {"class-t1": identical, "class-t2": {k: dict(v) for k, v in identical.items()}}
    baseline = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}
    class_aggregate, class_query, class_neighborhood, *_ = _run_helper(songs, classes, baseline)

    for ruler in ("artist", "genre", "head"):
        assert _aggregate(class_aggregate, "class-t1", ruler) == _aggregate(class_aggregate, "class-t2", ruler)
    assert _neighborhood(class_neighborhood, "class-t1", "song-q") == _neighborhood(
        class_neighborhood, "class-t2", "song-q"
    )
    assert class_query  # query rows exist for both classes


# ---------------------------------------------------------------------------
# D — mutating one song's representation prevents the collapse
# ---------------------------------------------------------------------------


def test_d_mutating_one_song_representation_prevents_collapse() -> None:
    songs = [
        {"song_id": "song-q", "artist": "art-a"},
        {"song_id": "song-a", "artist": "art-a"},
        {"song_id": "song-b", "artist": "art-b"},
    ]
    identical = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }
    mutated_query = {
        "song-q": {"song-a": 0.1, "song-b": 0.9},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }
    classes = {
        "class-t1": identical,
        "class-t2": {k: dict(v) for k, v in identical.items()},
        "class-t2-mutated": mutated_query,
    }
    baseline = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}
    class_aggregate, _query, class_neighborhood, *_ = _run_helper(songs, classes, baseline)

    assert _aggregate(class_aggregate, "class-t1", "artist") == _aggregate(class_aggregate, "class-t2", "artist")
    assert _aggregate(class_aggregate, "class-t1", "artist") != _aggregate(
        class_aggregate, "class-t2-mutated", "artist"
    )
    # The mutated class retains its own distinct neighborhood set.
    assert _neighborhood(class_neighborhood, "class-t1", "song-q")[0][1] == "song-a"
    assert _neighborhood(class_neighborhood, "class-t2-mutated", "song-q")[0][1] == "song-b"


# ---------------------------------------------------------------------------
# F — baseline relevance is by song identity, not representation id
# ---------------------------------------------------------------------------


def test_f_baseline_same_artist_candidate_relevant_by_song_identity() -> None:
    songs = [
        {"song_id": "song-q", "artist": "art-a"},
        {"song_id": "song-a", "artist": "art-a"},
        {"song_id": "song-b", "artist": "art-b"},
    ]
    classes = {
        "class-t1": {
            "song-q": {"song-a": 0.1, "song-b": 0.9},
            "song-a": {"song-q": 0.1, "song-b": 0.9},
            "song-b": {"song-q": 0.9, "song-a": 0.1},
        }
    }
    # Baseline vectors make the same-artist candidate the nearest neighbor; its
    # baseline representation id ("base:song-a") is unrelated to the class rep id
    # ("rep:song-a"), so relevance can only succeed by song identity.
    baseline = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}
    _ca, _cq, _cn, baseline_aggregate, baseline_query, baseline_neighborhood = _run_helper(songs, classes, baseline)

    assert (
        _representation("song-a", rid="base:song-a").search_representation_id
        != _representation("song-a").search_representation_id
    )

    artist_rows = [row for row in baseline_aggregate if row.ruler == "artist"]
    assert artist_rows and all(row.backbone == _BACKBONE for row in artist_rows)

    q_mrr = [
        row.value
        for row in baseline_query
        if row.query_song_id == "song-q" and row.ruler == "artist" and row.metric == "mrr"
    ]
    assert q_mrr == [pytest.approx(1.0)]
    q_neighbors = [row for row in baseline_neighborhood if row.query_song_id == "song-q"]
    assert min(q_neighbors, key=lambda row: row.rank).candidate_song_id == "song-a"


# ---------------------------------------------------------------------------
# H — retained top-100 window never limits the complete-ranking MRR
# ---------------------------------------------------------------------------


def test_h_first_relevant_beyond_retained_bound_uses_complete_ranking_rank() -> None:
    candidate_count = 104  # 103 unrelated + one relevant, strictly beyond the top 100
    relevant = "song-r"
    others = [f"candidate-{i:03d}" for i in range(candidate_count - 1)]
    songs = [{"song_id": "song-q", "artist": "art-a"}, {"song_id": relevant, "artist": "art-a"}]
    songs += [{"song_id": name, "artist": f"art-{name}"} for name in others]

    # The relevant candidate is the single lowest-scoring neighbor, so it lands at
    # rank 104 (1-based) while the browsing window keeps only the top 100.
    q_scores = {name: 0.9 - i * 0.001 for i, name in enumerate(others)}
    q_scores[relevant] = 0.01
    classes = {
        "class-t1": {
            "song-q": q_scores,
            relevant: {"song-q": 1.0},
            **{name: {"song-q": 1.0} for name in others},
        }
    }
    baseline = {"song-q": [[1.0, 0.0]], relevant: [[0.9, 0.1]]}
    baseline.update({name: [[1.0, 0.0]] for name in others})

    _ca, class_query, class_neighborhood, _ba, _bq, _bn = _run_helper(songs, classes, baseline)

    mrr_rows = [
        row.value
        for row in class_query
        if row.corpus_search_class_id == "class-t1"
        and row.query_song_id == "song-q"
        and row.ruler == "artist"
        and row.metric == "mrr"
    ]
    assert mrr_rows == [pytest.approx(1.0 / 104.0)]

    retained = _neighborhood(class_neighborhood, "class-t1", "song-q")
    assert len(retained) == _NEIGHBORHOOD_SIZE
    assert relevant not in {candidate for _rank, candidate in retained}
    assert [rank for rank, _candidate in retained] == list(range(_NEIGHBORHOOD_SIZE))


# ---------------------------------------------------------------------------
# Owner-level collapse: equal thresholds publish one retrieval result source
# ---------------------------------------------------------------------------

_PIPE_STREAMS = {
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
        self.stream = np.asarray(_PIPE_STREAMS[song_id], dtype=np.float32)


class _Store:
    def __init__(self, observations) -> None:
        self.observations = {observation.identity.song_id: observation for observation in observations}

    def load_committed_observation(self, song_id, backbone):
        assert backbone == _BACKBONE
        return self.observations[song_id]

    def batch_gather(self, song_id, backbone, indices, *, forbid_duplicates):
        assert forbid_duplicates is True
        assert backbone == _BACKBONE
        return np.asarray(self.observations[song_id].stream[list(indices)], dtype=np.float32)


def _constant_scorer():
    def score(_query, _weights, _candidate):
        return SimpleNamespace(finite=True, score=0.5)

    return score


_PIPE_LABELS = {
    "song-1": ("art", "rock", ("h1",)),
    "song-2": ("art", "rock", ("h1",)),
    "song-3": ("other", "jazz", ("h2",)),
}


def _pipeline_result() -> object:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    observations = [_Observation(con, song_id) for song_id in ("song-1", "song-2", "song-3")]
    items = []
    digest = None
    for observation in observations:
        song_id = observation.identity.song_id
        record = write_geometry(observation, GeometryProfile.current(), _RUN_ID)
        digest = record.identity.numerical_profile_digest
        artist, genre, head_label = _PIPE_LABELS[song_id]
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
                artist=artist,
                genre=genre,
                head_label=head_label,
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
        numerical_profile_digest=digest,
    )
    result = analyze_geometry_corpus(
        request,
        con=con,
        stream_store=_Store(observations),
        profile=GeometryProfile.current(),
        scoring=_constant_scorer(),
    )
    con.close()
    return result


def test_c_owner_collapses_equal_thresholds_into_one_retrieval_source() -> None:
    result = _pipeline_result()

    class_ids = [row.corpus_search_class_id for row in result.threshold_class_map]
    distinct = set(class_ids)
    assert 0 < len(distinct) < len(class_ids)  # some thresholds genuinely collapse

    # One aggregate metric block per (class, ruler, metric) — never per threshold.
    aggregate_keys = [(row.corpus_search_class_id, row.ruler, row.metric) for row in result.class_aggregate_metrics]
    assert len(aggregate_keys) == len(set(aggregate_keys))
    assert len(aggregate_keys) == len(distinct) * 3 * 5
    assert {key[0] for key in aggregate_keys} == distinct

    # One per-query metric row per (class, query, ruler, metric).
    query_keys = [
        (row.corpus_search_class_id, row.query_song_id, row.ruler, row.metric) for row in result.class_query_metrics
    ]
    assert len(query_keys) == len(set(query_keys))
    assert {key[0] for key in query_keys} <= distinct

    # One neighborhood set per (class, query), never multiplied across equal thresholds.
    neighborhood_keys = [
        (row.corpus_search_class_id, row.query_song_id, row.candidate_song_id) for row in result.class_neighborhoods
    ]
    assert len(neighborhood_keys) == len(set(neighborhood_keys))

    # The threshold-independent baseline is a single backbone-scoped block.
    baseline_rulers = {row.ruler for row in result.baseline_aggregate_metrics}
    assert baseline_rulers == {"artist", "genre", "head"}
    assert len(result.baseline_aggregate_metrics) == 3 * 5
    assert {row.backbone for row in result.baseline_aggregate_metrics} == {_BACKBONE}


def test_c_baseline_is_threshold_and_class_independent() -> None:
    songs = [
        {"song_id": "song-q", "artist": "art-a"},
        {"song_id": "song-a", "artist": "art-a"},
        {"song_id": "song-b", "artist": "art-b"},
    ]
    baseline = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}
    populated = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }

    _ca, _cq, _cn, with_classes_agg, with_classes_query, with_classes_nb = _run_helper(
        songs, {"class-t1": populated}, baseline
    )
    _ea, _eq, _en, empty_agg, empty_query, empty_nb = _run_helper(songs, {}, baseline)

    # Baseline is computed once for the fixed corpus, independent of how many
    # classes/thresholds exist: the rows are byte-identical with zero classes.
    assert with_classes_agg == empty_agg
    assert with_classes_query == empty_query
    assert with_classes_nb == empty_nb
    assert len(empty_agg) == 3 * 5
    assert {row.backbone for row in empty_agg} == {_BACKBONE}
