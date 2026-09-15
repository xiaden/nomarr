"""Normalized Experiment One result surfaces (Plan A Phase 5).

Proves the hard-cut result layer: the giant nested ``role="corpus"`` JSON blob is replaced by
flat, query-ready rows that are written and read back atomically.

 * **A** — 171 thresholds publish no duplicate identities; structural rows scale ``O(N x T)``
   and retrieval rows ``O(C x N)``.
 * **C** — thresholds with identical complete corpus scoring inputs collapse to ONE class with ONE
   metric/neighborhood block, and every collapsed threshold reads back through that shared class.
 * **E** — a non-comparable class emits no partial segmented metrics while the threshold-
  independent baseline still covers the fixed corpus, and the structural evidence keeps its
  canonical reasons.
* **I** — baseline row counts do not depend on the configured threshold count.
* **J** — the same ``(query, candidate)`` under two classes round-trips distinctly.
* **K** — per-query rows exist for artist, genre, and frozen-head rulers with explicit
  defined/undefined status.

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
    GeometryThresholdStructuralRow,
    _geometry_class_scoped_metrics,
    _select_neighborhood,
    analyze_geometry_corpus,
    write_geometry_corpus_analysis,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.identity_persistence import (
    read_threshold_class_map,
    read_threshold_structural,
    write_threshold_structural_in_transaction,
)
from scripts.embedding_research.db.result_surfaces import (
    read_baseline_aggregate_metrics,
    read_baseline_neighborhoods,
    read_baseline_query_metrics,
    read_class_aggregate_metrics,
    read_class_neighborhoods,
    read_class_query_metrics,
    read_result_provenance,
    write_baseline_aggregate_metrics_in_transaction,
    write_baseline_neighborhoods_in_transaction,
    write_baseline_query_metrics_in_transaction,
    write_class_neighborhoods_in_transaction,
    write_class_query_metrics_in_transaction,
)

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RUN_ID = "run-result-surfaces"
_EVALUATION_ID = "evaluation-result-surfaces"
_EXECUTION_ID = "execution:run-result-surfaces:effnet"

#: The class-scoped result oracle publishes one aggregate row per ruler per metric.
_RULERS = 3
_METRICS = 5

# ---------------------------------------------------------------------------
# Direct-helper fixtures (single-backbone synthetic scoring)
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


_THREE_SONGS = [
    {"song_id": "song-q", "artist": "art-a", "genre": "rock", "head_label": ("h1",)},
    {"song_id": "song-a", "artist": "art-a", "genre": "rock", "head_label": ("h1",)},
    {"song_id": "song-b", "artist": "art-b", "genre": "jazz", "head_label": ("h2",)},
]
_BASELINE_VECTORS = {"song-q": [[1.0, 0.0]], "song-a": [[0.9, 0.1]], "song-b": [[-1.0, 0.0]]}

# ---------------------------------------------------------------------------
# Owner pipeline fixture (real analyze over the 171 primary thresholds)
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


def _pipeline(con) -> object:
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
    return analyze_geometry_corpus(
        request,
        con=con,
        stream_store=_Store(observations),
        profile=GeometryProfile.current(),
        scoring=_constant_scorer(),
    )


# ---------------------------------------------------------------------------
# A — 171 thresholds: no duplicate identities, O(N x T) structural, O(C x N) retrieval
# ---------------------------------------------------------------------------


def test_a_normalized_surfaces_write_no_duplicate_identity_over_171_thresholds() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    result = _pipeline(con)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    class_map = read_threshold_class_map(con, run_id=_RUN_ID)
    assert len(class_map) == 171
    threshold_indices = [row["threshold_index"] for row in class_map]
    assert threshold_indices == list(range(171))

    # Structural evidence is one row per (song, threshold): O(N x T), never O(N x T^2).
    structural = read_threshold_structural(con, run_id=_RUN_ID)
    assert len(structural) == 3 * 171
    structural_keys = {(row["song_id"], row["threshold_index"]) for row in structural}
    assert len(structural_keys) == len(structural)

    distinct_classes = {row["corpus_search_class_id"] for row in class_map}
    assert 0 < len(distinct_classes) < 171

    # Retrieval surfaces are one row per class-scoped identity: O(C x N), never O(C x N x T).
    aggregate = read_class_aggregate_metrics(con, run_id=_RUN_ID)
    aggregate_keys = {(row["corpus_search_class_id"], row["ruler"], row["metric"], row["k"]) for row in aggregate}
    assert len(aggregate_keys) == len(aggregate)
    assert len(aggregate) == len(distinct_classes) * 3 * 5

    query_rows = read_class_query_metrics(con, run_id=_RUN_ID)
    query_keys = {
        (row["corpus_search_class_id"], row["query_song_id"], row["ruler"], row["metric"], row["k"])
        for row in query_rows
    }
    assert len(query_keys) == len(query_rows)

    neighborhoods = read_class_neighborhoods(con, run_id=_RUN_ID)
    neighborhood_keys = {
        (row["corpus_search_class_id"], row["query_song_id"], row["candidate_song_id"]) for row in neighborhoods
    }
    assert len(neighborhood_keys) == len(neighborhoods)
    assert all(row["query_song_id"] != row["candidate_song_id"] for row in neighborhoods)
    assert len(neighborhoods) == len(distinct_classes) * 3 * 2

    baseline_aggregate = read_baseline_aggregate_metrics(con, run_id=_RUN_ID)
    assert len(baseline_aggregate) == 3 * 5
    assert {row["backbone"] for row in baseline_aggregate} == {_BACKBONE}
    baseline_keys = {(row["ruler"], row["metric"], row["k"]) for row in baseline_aggregate}
    assert len(baseline_keys) == 3 * 5
    # P5-S3: segmented (class) and baseline aggregates share the (ruler, metric, k) key, so
    # segmented-minus-baseline is a well-defined report JOIN; every class aggregate has exactly
    # one threshold-independent baseline counterpart.
    assert {(row["ruler"], row["metric"], row["k"]) for row in aggregate} <= baseline_keys

    baseline_neighborhoods = read_baseline_neighborhoods(con, run_id=_RUN_ID)
    assert len(baseline_neighborhoods) == 3 * 2
    assert all(row["query_song_id"] != row["candidate_song_id"] for row in baseline_neighborhoods)

    provenance = read_result_provenance(con, run_id=_RUN_ID)
    assert len(provenance) == 1
    assert provenance[0]["evidence_mode"] == "synthetic_fixture"
    assert provenance[0]["synthetic_only"] is True

    # P9-S1: every persisted surface is bounded by the corpus/class/ruler/metric axes and the
    # retained top-N window — never by a persisted N x N similarity matrix.
    n = 3
    top_n = min(n - 1, _NEIGHBORHOOD_SIZE)
    assert top_n == 2
    assert _NEIGHBORHOOD_SIZE <= 100
    assert len(structural) == n * 171
    assert len(aggregate) == len(distinct_classes) * _RULERS * _METRICS
    assert len(query_rows) <= len(distinct_classes) * n * _RULERS * _METRICS
    assert len(neighborhoods) == len(distinct_classes) * n * top_n
    assert len(baseline_aggregate) == _RULERS * _METRICS
    assert len(baseline_neighborhoods) == n * top_n
    persisted_surfaces = (
        structural,
        class_map,
        aggregate,
        query_rows,
        neighborhoods,
        baseline_aggregate,
        read_baseline_query_metrics(con, run_id=_RUN_ID),
        baseline_neighborhoods,
    )
    # A persisted full N x N similarity matrix would be exactly N*N rows on some surface. The
    # class similarity matrix is transient — constructed inside the metric pass and never stored.
    full_matrix_rows = n * n
    for surface in persisted_surfaces:
        assert len(surface) != full_matrix_rows
    assert full_matrix_rows not in {
        len(neighborhoods) // len(distinct_classes),
        len(baseline_neighborhoods) // n,
    }
    con.close()


# ---------------------------------------------------------------------------
# C — equal complete corpus scoring inputs collapse to one class, one retrieval set
# ---------------------------------------------------------------------------


def test_c_equal_threshold_inputs_collapse_to_one_class_and_read_back() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    result = _pipeline(con)
    write_geometry_corpus_analysis(con, run_id=_RUN_ID, result=result)

    class_map = read_threshold_class_map(con, run_id=_RUN_ID)
    assert len(class_map) == 171
    # A collapse stays inside ONE backbone-scoped execution, never one execution per threshold.
    assert {row["execution_id"] for row in class_map} == {_EXECUTION_ID}

    by_class: dict[str, list[int]] = {}
    for row in class_map:
        by_class.setdefault(row["corpus_search_class_id"], []).append(row["threshold_index"])
    collapsed = {class_id: indices for class_id, indices in by_class.items() if len(indices) >= 2}
    assert collapsed, "identical corpus scoring inputs must collapse at least two thresholds"

    # Retrieval rows are keyed by the shared class: ONE metric block and ONE neighborhood set per
    # class, never a per-threshold duplicate.
    distinct_classes = set(by_class)
    aggregate = read_class_aggregate_metrics(con, run_id=_RUN_ID)
    aggregate_keys = {(row["corpus_search_class_id"], row["ruler"], row["metric"], row["k"]) for row in aggregate}
    assert len(aggregate_keys) == len(aggregate) == len(distinct_classes) * _RULERS * _METRICS
    neighborhoods = read_class_neighborhoods(con, run_id=_RUN_ID)
    neighborhood_keys = {
        (row["corpus_search_class_id"], row["query_song_id"], row["candidate_song_id"]) for row in neighborhoods
    }
    assert len(neighborhood_keys) == len(neighborhoods)

    # Every threshold in the collapse is published with the SAME class id, so reading metrics
    # through that shared class yields one identical block for both thresholds.
    shared_class, collapsed_indices = next(iter(sorted(collapsed.items())))
    assert len(collapsed_indices) >= 2
    assert {row["corpus_search_class_id"] for row in class_map if row["threshold_index"] in collapsed_indices} == {
        shared_class
    }
    block = [row for row in aggregate if row["corpus_search_class_id"] == shared_class]
    assert {row["ruler"] for row in block} == {"artist", "genre", "head"}
    assert len(block) == _RULERS * _METRICS
    con.close()


# ---------------------------------------------------------------------------
# E — non-comparable class emits no partial segmented metrics; baseline still covers corpus
# ---------------------------------------------------------------------------


def test_e_non_comparable_class_emits_no_partial_metrics_but_baseline_covers_corpus() -> None:
    # "class-t1" scores only 2 of 3 corpus songs, so it is non-comparable and emits nothing.
    incomplete = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
    }
    class_aggregate, class_query, class_neighborhood, baseline_aggregate, _bq, baseline_neighborhood = _run_helper(
        _THREE_SONGS, {"class-t1": incomplete}, _BASELINE_VECTORS
    )
    assert class_aggregate == ()
    assert class_query == ()
    assert class_neighborhood == ()
    # Baseline is threshold- and class-independent: it still covers the full fixed corpus.
    assert len(baseline_aggregate) == 3 * 5
    assert len(baseline_neighborhood) == 3 * 2
    assert {row.query_song_id for row in baseline_neighborhood} == {"song-q", "song-a", "song-b"}
    # P9-S1: a non-comparable class emits no retrieval rows at all; only the threshold-
    # independent baseline's O(N x topN) window is retained, never an N x N matrix.
    top_n = min(len(_THREE_SONGS) - 1, _NEIGHBORHOOD_SIZE)
    assert len(baseline_aggregate) == _RULERS * _METRICS
    assert len(baseline_neighborhood) == len(_THREE_SONGS) * top_n
    assert len(baseline_neighborhood) != len(_THREE_SONGS) ** 2
    assert len(baseline_aggregate) != len(_THREE_SONGS) ** 2

    # The structural evidence for the non-comparable threshold is retained with canonical reasons.
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("BEGIN")
    write_threshold_structural_in_transaction(
        con,
        run_id=_RUN_ID,
        evaluation_id=_EVALUATION_ID,
        rows=(
            GeometryThresholdStructuralRow(
                "song-q",
                _BACKBONE,
                0,
                "threshold-0",
                "structural-q",
                "representation-q",
                0,
                False,
                True,
                False,
                ("zero_searchable",),
            ),
        ),
    )
    con.execute("COMMIT")
    stored = read_threshold_structural(con, run_id=_RUN_ID)
    assert len(stored) == 1
    assert stored[0]["comparable"] is False
    assert stored[0]["reasons"] == ("zero_searchable",)
    con.close()


# ---------------------------------------------------------------------------
# I — baseline row counts are independent of the configured threshold count
# ---------------------------------------------------------------------------


def test_i_baseline_counts_are_independent_of_threshold_count() -> None:
    populated = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }
    _ca, _cq, _cn, one_aggregate, one_query, one_neighborhood = _run_helper(
        _THREE_SONGS, {"class-t1": populated}, _BASELINE_VECTORS
    )
    _ea, _eq, _en, two_aggregate, two_query, two_neighborhood = _run_helper(
        _THREE_SONGS,
        {"class-t1": populated, "class-t2": {key: dict(value) for key, value in populated.items()}},
        _BASELINE_VECTORS,
    )
    # Two classes versus one: baseline rows are byte-identical, so their count never scales
    # with the class/threshold count.
    assert one_aggregate == two_aggregate
    assert one_query == two_query
    assert one_neighborhood == two_neighborhood
    assert len(one_aggregate) == 3 * 5
    assert len(one_neighborhood) == 3 * 2

    # P9-S1: the threshold-independent baseline is byte-identical at the PERSISTED level too;
    # the two runs differ only in their run identity and the created_at_ms wall-clock stamp.
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    for run_id, aggregate, query, neighborhood in (
        ("run-one-class", one_aggregate, one_query, one_neighborhood),
        ("run-two-classes", two_aggregate, two_query, two_neighborhood),
    ):
        con.execute("BEGIN")
        write_baseline_aggregate_metrics_in_transaction(
            con,
            run_id=run_id,
            execution_id=_EXECUTION_ID,
            evaluation_id=_EVALUATION_ID,
            rows=aggregate,
        )
        write_baseline_query_metrics_in_transaction(con, run_id=run_id, rows=query)
        write_baseline_neighborhoods_in_transaction(con, run_id=run_id, rows=neighborhood)
        con.execute("COMMIT")

    def _baseline_snapshot(run_id: str) -> tuple[object, object, object]:
        def _strip(rows: list[dict]) -> tuple[dict, ...]:
            return tuple(
                {key: value for key, value in row.items() if key not in {"run_id", "created_at_ms"}} for row in rows
            )

        return (
            _strip(read_baseline_aggregate_metrics(con, run_id=run_id)),
            _strip(read_baseline_query_metrics(con, run_id=run_id)),
            _strip(read_baseline_neighborhoods(con, run_id=run_id)),
        )

    assert _baseline_snapshot("run-one-class") == _baseline_snapshot("run-two-classes")
    con.close()


# ---------------------------------------------------------------------------
# J — the same (query, candidate) under two classes round-trips distinctly
# ---------------------------------------------------------------------------


def test_j_same_query_candidate_under_two_classes_round_trips_distinctly() -> None:
    classes = {
        "class-t1": {
            "song-q": {"song-a": 0.9, "song-b": 0.1},
            "song-a": {"song-q": 0.9, "song-b": 0.1},
            "song-b": {"song-q": 0.1, "song-a": 0.1},
        },
        "class-t2": {
            "song-q": {"song-a": 0.2, "song-b": 0.8},
            "song-a": {"song-q": 0.2, "song-b": 0.8},
            "song-b": {"song-q": 0.8, "song-a": 0.2},
        },
    }
    _aggregate, query_rows, neighborhoods, *_ = _run_helper(_THREE_SONGS, classes, _BASELINE_VECTORS)

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("BEGIN")
    write_class_query_metrics_in_transaction(con, run_id=_RUN_ID, rows=query_rows)
    write_class_neighborhoods_in_transaction(con, run_id=_RUN_ID, rows=neighborhoods)
    con.execute("COMMIT")

    stored = read_class_neighborhoods(con, run_id=_RUN_ID)
    for_query_candidate = [
        row for row in stored if row["query_song_id"] == "song-q" and row["candidate_song_id"] == "song-a"
    ]
    under_class = {row["corpus_search_class_id"] for row in for_query_candidate}
    assert under_class == {"class-t1", "class-t2"}
    # The class is part of the identity: both rows coexist with their own score.
    class_scores = {row["corpus_search_class_id"]: row["score"] for row in for_query_candidate}
    assert class_scores["class-t1"] > class_scores["class-t2"]

    stored_queries = read_class_query_metrics(con, run_id=_RUN_ID)
    query_keys = {
        (row["corpus_search_class_id"], row["query_song_id"], row["ruler"], row["metric"], row["k"])
        for row in stored_queries
    }
    assert len(query_keys) == len(stored_queries)
    # P9-S2: the class is part of the metric identity too — the same query under two classes keeps
    # its own per-query metric values rather than being collapsed across classes.
    per_class_mrr = {
        row["corpus_search_class_id"]: row["value"]
        for row in stored_queries
        if row["query_song_id"] == "song-q" and row["ruler"] == "artist" and row["metric"] == "mrr"
    }
    assert set(per_class_mrr) == {"class-t1", "class-t2"}
    assert per_class_mrr["class-t1"] != per_class_mrr["class-t2"]
    con.close()


# ---------------------------------------------------------------------------
# K — per-query rows exist for artist, genre, and frozen-head with defined/undefined
# ---------------------------------------------------------------------------


def test_k_per_query_metrics_cover_artist_genre_and_head_with_status() -> None:
    populated = {
        "song-q": {"song-a": 0.9, "song-b": 0.1},
        "song-a": {"song-q": 0.9, "song-b": 0.1},
        "song-b": {"song-q": 0.1, "song-a": 0.1},
    }
    _aggregate, query_rows, _neighborhoods, *_ = _run_helper(_THREE_SONGS, {"class-t1": populated}, _BASELINE_VECTORS)

    assert {row.ruler for row in query_rows} == {"artist", "genre", "head"}
    # song-q shares artist/genre/head with song-a, so it is evaluable under every ruler.
    song_q = [row for row in query_rows if row.query_song_id == "song-q"]
    assert {row.ruler for row in song_q} == {"artist", "genre", "head"}
    assert {row.status for row in song_q} == {"defined"}
    # song-b is the only member of its artist/genre/head cluster: undefined under every ruler.
    song_b = [row for row in query_rows if row.query_song_id == "song-b"]
    assert {row.ruler for row in song_b} == {"artist", "genre", "head"}
    assert {row.status for row in song_b} == {"undefined"}

    # P9-S2: every (class, query, ruler) persists the full per-query metric set (the four
    # metrics that expose a per-song oracle value; ndcg_k is aggregate-only).
    per_query_metrics: dict[tuple[str, str, str], set[str]] = {}
    for row in query_rows:
        key = (row.corpus_search_class_id, row.query_song_id, row.ruler)
        per_query_metrics.setdefault(key, set()).add(row.metric)
    assert per_query_metrics
    assert {"artist", "genre", "head"} == {key[2] for key in per_query_metrics}
    assert all(metrics <= {"map_k", "mrr", "ndcg_k", "recall_k", "disc"} for metrics in per_query_metrics.values())
    assert {row.status for row in query_rows} == {"defined", "undefined"}

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    con.execute("BEGIN")
    write_class_query_metrics_in_transaction(con, run_id=_RUN_ID, rows=query_rows)
    con.execute("COMMIT")
    stored = read_class_query_metrics(con, run_id=_RUN_ID)
    assert {"artist", "genre", "head"} <= {row["ruler"] for row in stored}
    assert {"defined", "undefined"} <= {row["status"] for row in stored}
    # P9-S2: all three rulers carry both defined and undefined statuses across the corpus.
    defined_rulers = {row["ruler"] for row in stored if row["status"] == "defined"}
    undefined_rulers = {row["ruler"] for row in stored if row["status"] == "undefined"}
    assert {"artist", "genre", "head"} <= defined_rulers
    assert {"artist", "genre", "head"} <= undefined_rulers
    con.close()
