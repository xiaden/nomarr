"""Plan C Phase 2 — performance and storage scaling envelope (surfaces A-G).

This module proves the normalized Experiment One result layer has a flat, bounded
persisted footprint.  Every assertion is exact: the row count of each surface is
pinned to a formula over the corpus size ``N``, the configured threshold count
``T``, the number of threshold classes ``C``, the ruler/metric axes, and the
retained top-``_NEIGHBORHOOD_SIZE`` browsing window.

The whole module runs on an in-memory DuckDB corpus driven by synthetic stream
doubles.  No real corpus, model, audio, ONNX, or CUDA is involved.

Scaling claims verified here:

* **P2-S1** — exact surface bounds at the production 171-threshold sweep and at a
  controlled owner-level corpus.
* **P2-S2** — no persisted surface stores a full ``N x N`` similarity matrix, no
  surface stores a per-threshold-expanded baseline copy, and the class similarity
  matrix exists only transiently inside the class-metric computation.
* **P2-S3** — doubling ``T`` (N fixed) and doubling ``N`` (T fixed) grow row counts
  linearly, never quadratically.

The primary threshold request is pinned by ``PrimaryThresholdRequest`` to indices
``0..170``.  The ``T``-doubling case therefore parameterizes the primary request
through a test-scoped ``PRIMARY_THRESHOLD_COUNT`` patch so the SAME production
``analyze_geometry_corpus`` -> ``write_geometry_corpus_analysis`` path runs at
``T = 8`` and ``T = 16``.  The ``N``-doubling case uses the production class-scoped
metric owner ``_geometry_class_scoped_metrics`` with ``N = 101`` and ``N = 202``
(above the retained-window cap, so ``topN`` is a constant 100 and the claim is
``O(N)`` rather than the pre-cap ``O(N * (N - 1))``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common import geometry_analysis, threshold_analysis
from scripts.embedding_research.common.geometry_analysis import (
    _NEIGHBORHOOD_SIZE,
    FrozenSearchRepresentation,
    GeometryCorpusRequest,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongAnalysis,
    GeometrySongRequest,
    GeometryThresholdClassRow,
    GeometryThresholdStructuralRow,
    _geometry_class_scoped_metrics,
    _select_neighborhood,
    analyze_geometry_corpus,
    write_geometry_corpus_analysis,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    PrimaryThresholdRequest,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import _schema as schema_module
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db import result_surfaces as result_surfaces_module
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.identity_persistence import (
    read_threshold_class_map,
    read_threshold_structural,
    write_threshold_class_map_in_transaction,
    write_threshold_structural_in_transaction,
)
from scripts.embedding_research.db.result_surfaces import (
    _BASELINE_AGGREGATE_METRIC_COLUMNS,
    _BASELINE_NEIGHBORHOOD_COLUMNS,
    read_baseline_aggregate_metrics,
    read_baseline_neighborhoods,
    read_baseline_query_metrics,
    read_class_aggregate_metrics,
    read_class_neighborhoods,
    read_class_query_metrics,
)

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RULERS = 3
_METRICS = 5

# ---------------------------------------------------------------------------
# Direct-helper fixtures (controlled N / C via the class-metric owner)
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
        evaluation_id="evaluation-scaling",
        execution_id=f"execution:run-scaling:{_BACKBONE}",
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


def _song_list(n: int) -> list[dict[str, object]]:
    return [
        {
            "song_id": f"song-{i:03d}",
            "artist": f"art-{i:03d}",
            "genre": f"genre-{i:03d}",
            "head_label": (f"head-{i:03d}",),
        }
        for i in range(n)
    ]


def _full_class(song_ids: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """One complete class: every query scores every other corpus song."""
    return {
        query: {candidate: 1.0 / (1.0 + abs(i - j)) for j, candidate in enumerate(song_ids) if j != i}
        for i, query in enumerate(song_ids)
    }


def _baseline_vectors(song_ids: tuple[str, ...]) -> dict[str, object]:
    return {song_id: [[1.0, 0.001 * index]] for index, song_id in enumerate(song_ids)}


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
        evaluation_id="evaluation-scaling",
        scoring_semantics_version=1,
        run_id="run-scaling",
        execution_id=f"execution:run-scaling:{_BACKBONE}",
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


# ---------------------------------------------------------------------------
# Owner pipeline fixture: real analyze -> write over synthetic streams
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


def _run_pipeline(con, *, run_id: str, t_count: int, song_ids: tuple[str, ...] = ("song-1", "song-2", "song-3")):
    """Run the production analyze -> write path at an arbitrary threshold count.

    ``PRIMARY_THRESHOLD_COUNT`` is patched only for the duration of request
    construction and analysis so the SAME production owner runs with ``T``
    thresholds; the persisted surfaces are produced by the unmodified writers.
    """
    with mock.patch.object(threshold_analysis, "PRIMARY_THRESHOLD_COUNT", t_count):
        threshold_request = PrimaryThresholdRequest(tuple(range(t_count)))
        observations = [_Observation(con, song_id) for song_id in song_ids]
        items = []
        digest = None
        for observation in observations:
            song_id = observation.identity.song_id
            record = write_geometry(observation, GeometryProfile.current(), run_id)
            digest = record.identity.numerical_profile_digest
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
            threshold_request=threshold_request,
            experiment="temporal_global",
            evaluation_id=f"evaluation:{run_id}",
            scoring_semantics_version=1,
            run_id=run_id,
            execution_id=f"execution:{run_id}:{_BACKBONE}",
            numerical_profile_digest=digest,
        )
        result = analyze_geometry_corpus(
            request,
            con=con,
            stream_store=_Store(observations),
            profile=GeometryProfile.current(),
            scoring=_constant_scorer(),
        )
    write_geometry_corpus_analysis(con, run_id=run_id, result=result)
    return result


def _surface_counts(con, *, run_id: str) -> dict[str, int]:
    return {
        "class_map": len(read_threshold_class_map(con, run_id=run_id)),
        "structural": len(read_threshold_structural(con, run_id=run_id)),
        "class_aggregate": len(read_class_aggregate_metrics(con, run_id=run_id)),
        "class_query": len(read_class_query_metrics(con, run_id=run_id)),
        "class_neighborhood": len(read_class_neighborhoods(con, run_id=run_id)),
        "baseline_aggregate": len(read_baseline_aggregate_metrics(con, run_id=run_id)),
        "baseline_query": len(read_baseline_query_metrics(con, run_id=run_id)),
        "baseline_neighborhood": len(read_baseline_neighborhoods(con, run_id=run_id)),
    }


def _write_threshold_surfaces(con, *, run_id: str, n: int, t: int) -> dict[str, int]:
    """Persist a synthetic threshold sweep through the real writers/readers."""
    evaluation_id = f"evaluation:{run_id}"
    map_rows = [
        GeometryThresholdClassRow(index, f"threshold:{index}", float(index), f"class-{index}", True, ())
        for index in range(t)
    ]
    structural_rows = [
        GeometryThresholdStructuralRow(
            f"song-{song:03d}",
            _BACKBONE,
            index,
            f"threshold:{index}",
            f"structural:{song}:{index}",
            f"rep:{song}:{index}",
            1,
            True,
            True,
            True,
            (),
        )
        for song in range(n)
        for index in range(t)
    ]
    con.execute("BEGIN")
    write_threshold_class_map_in_transaction(
        con,
        run_id=run_id,
        evaluation_id=evaluation_id,
        execution_id=f"execution:{run_id}:{_BACKBONE}",
        experiment="temporal_global",
        rows=map_rows,
    )
    write_threshold_structural_in_transaction(con, run_id=run_id, evaluation_id=evaluation_id, rows=structural_rows)
    con.execute("COMMIT")
    return {
        "class_map": len(read_threshold_class_map(con, run_id=run_id)),
        "structural": len(read_threshold_structural(con, run_id=run_id)),
    }


# ---------------------------------------------------------------------------
# P2-S1 — exact surface bounds
# ---------------------------------------------------------------------------


def test_p2s1_exact_surface_bounds_at_production_threshold_sweep() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _run_pipeline(con, run_id="run-scaling-171", t_count=171)
    counts = _surface_counts(con, run_id="run-scaling-171")

    n = 3
    t = 171
    top_n = min(n - 1, _NEIGHBORHOOD_SIZE)
    assert top_n == 2
    assert _NEIGHBORHOOD_SIZE <= 100

    # A — one map row per configured threshold regardless of collapse; structural
    # evidence is one row per (song, threshold), never T x T.
    assert counts["class_map"] == t
    assert counts["structural"] == n * t
    assert counts["structural"] != n * t * t
    assert counts["class_map"] != t * t

    # C/D/E — aggregate rows are one per comparable class per ruler per metric.
    aggregate = read_class_aggregate_metrics(con, run_id="run-scaling-171")
    classes = {row["corpus_search_class_id"] for row in aggregate}
    c = len(classes)
    assert 0 < c < t
    assert counts["class_aggregate"] == c * _RULERS * _METRICS

    # per-query rows never exceed one per class/query/ruler/metric.
    assert counts["class_query"] <= c * n * _RULERS * _METRICS
    assert counts["class_query"] > 0
    # E — one neighborhood row per class/query/retained candidate, bounded by topN.
    assert counts["class_neighborhood"] == c * n * top_n

    # F — baseline is a single threshold-independent block over the fixed corpus.
    assert counts["baseline_aggregate"] == _RULERS * _METRICS
    assert counts["baseline_query"] <= n * _RULERS * _METRICS
    assert counts["baseline_query"] > 0
    assert counts["baseline_neighborhood"] == n * top_n

    # P2-S2 — no persisted surface equals an N x N matrix.
    for name, count in counts.items():
        assert count != n * n, f"surface {name} persisted an N x N matrix shape"
    con.close()


def test_p2s1_exact_surface_bounds_at_controlled_owner_corpus() -> None:
    n = 4
    c = 3
    songs = _song_list(n)
    song_ids = tuple(str(song["song_id"]) for song in songs)
    classes = {f"class-{index}": _full_class(song_ids) for index in range(c)}
    class_aggregate, class_query, class_neighborhood, baseline_aggregate, baseline_query, baseline_neighborhood = (
        _run_helper(songs, classes, _baseline_vectors(song_ids))
    )

    top_n = min(n - 1, _NEIGHBORHOOD_SIZE)
    assert len(class_aggregate) == c * _RULERS * _METRICS
    # Undefined rulers (single-song clusters) still publish finite per-query rows for the
    # metrics that carry a per-song oracle value, bounded by one row per ruler/metric.
    assert 0 < len(class_query) <= c * n * _RULERS * _METRICS
    assert len(class_neighborhood) == c * n * top_n
    assert len(baseline_aggregate) == _RULERS * _METRICS
    assert 0 < len(baseline_query) <= n * _RULERS * _METRICS
    assert len(baseline_neighborhood) == n * top_n
    # The owner never materializes an N x N matrix as a result surface.
    assert len(class_neighborhood) != n * n
    assert len(baseline_neighborhood) != n * n


# ---------------------------------------------------------------------------
# P2-S2 — no persisted N x N matrix, no threshold-expanded baseline, transient matrix
# ---------------------------------------------------------------------------


def _active_sources() -> list[Path]:
    root = Path(geometry_analysis.__file__).resolve().parents[1]
    return [path for path in root.rglob("*.py") if "tests" not in path.parts]


def test_p2s2_no_persisted_surface_stores_matrix_or_threshold_expanded_baseline() -> None:
    # Baseline tables carry no threshold/class scoping column at all.
    assert not any("threshold" in column or "class" in column for column in _BASELINE_AGGREGATE_METRIC_COLUMNS)
    assert not any("threshold" in column or "class" in column for column in _BASELINE_NEIGHBORHOOD_COLUMNS)

    # The schema defines no matrix/similarity table or column.
    schema_text = Path(schema_module.__file__).read_text(encoding="utf-8").lower()
    assert "matrix" not in schema_text
    assert "similarity" not in schema_text

    # No writer module imports or references a matrix materialization.
    result_surfaces_text = Path(result_surfaces_module.__file__).read_text(encoding="utf-8").lower()
    for token in ("numpy", "np.", "similarity", "matrix", "cosine"):
        assert token not in result_surfaces_text

    # Baseline row counts do not scale with the threshold count: a per-threshold-expanded
    # baseline would have `_RULERS * _METRICS * T` rows.
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _run_pipeline(con, run_id="run-scaling-baseline", t_count=171)
    counts = _surface_counts(con, run_id="run-scaling-baseline")
    assert counts["baseline_aggregate"] == _RULERS * _METRICS
    assert counts["baseline_aggregate"] != _RULERS * _METRICS * 171
    assert counts["baseline_neighborhood"] == 3 * min(3 - 1, _NEIGHBORHOOD_SIZE)
    assert counts["baseline_neighborhood"] != 3 * min(3 - 1, _NEIGHBORHOOD_SIZE) * 171
    con.close()


def test_p2s2_similarity_matrix_is_transient_and_writer_free() -> None:
    geo_path = Path(geometry_analysis.__file__).resolve()
    references = [
        (path.resolve(), lineno)
        for path in _active_sources()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "_class_similarity_matrix" in line
    ]
    assert references, "the transient class similarity matrix must still exist"
    assert {path for path, _ in references} == {geo_path}, "similarity matrix must be defined only in geometry_analysis"

    tree = ast.parse(geo_path.read_text(encoding="utf-8"))
    definitions = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_class_similarity_matrix"
    ]
    owners = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_geometry_class_scoped_metrics"
    ]
    assert len(definitions) == 1
    assert len(owners) == 1
    owner = owners[0]
    calls = [
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_class_similarity_matrix"
    ]
    assert len(calls) == 1, "the matrix must be constructed exactly once, inside the class-metric pass"
    assert owner.lineno <= calls[0].lineno <= (owner.end_lineno or owner.lineno)

    # No writer function anywhere in the active source tree references the transient matrix.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("write_"):
            names = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
            assert "_class_similarity_matrix" not in names
    for path in _active_sources():
        if path.resolve() == geo_path:
            continue
        assert "_class_similarity_matrix" not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# P2-S3 — linear (never quadratic) growth
# ---------------------------------------------------------------------------


def test_p2s3_threshold_doubling_is_linear_not_quadratic() -> None:
    n = 3
    small = duckdb.connect(":memory:")
    ensure_schema(small)
    _run_pipeline(small, run_id="run-scaling-t8", t_count=8)
    small_counts = _surface_counts(small, run_id="run-scaling-t8")
    small.close()

    large = duckdb.connect(":memory:")
    ensure_schema(large)
    _run_pipeline(large, run_id="run-scaling-t16", t_count=16)
    large_counts = _surface_counts(large, run_id="run-scaling-t16")
    large.close()

    # T -> 2T with N fixed: map and structural rows exactly double.
    assert small_counts["class_map"] == 8
    assert large_counts["class_map"] == 16
    assert large_counts["class_map"] == 2 * small_counts["class_map"]
    assert small_counts["structural"] == n * 8
    assert large_counts["structural"] == n * 16
    assert large_counts["structural"] == 2 * small_counts["structural"]

    # A T^2 surface would be ~4x on doubling; the observed growth is strictly linear.
    assert large_counts["structural"] < 4 * small_counts["structural"]
    assert large_counts["structural"] != n * 16 * 16
    assert large_counts["class_map"] != 16 * 16

    # Baseline is threshold-independent: identical row counts at both T.
    assert small_counts["baseline_aggregate"] == large_counts["baseline_aggregate"] == _RULERS * _METRICS
    assert small_counts["baseline_neighborhood"] == large_counts["baseline_neighborhood"]


def test_p2s3_song_doubling_is_linear_not_quadratic() -> None:
    c = 1
    sizes = (101, 202)
    top_n = _NEIGHBORHOOD_SIZE
    observed: dict[int, tuple[int, int, int, int]] = {}
    for n in sizes:
        songs = _song_list(n)
        song_ids = tuple(str(song["song_id"]) for song in songs)
        classes = {f"class-{index}": _full_class(song_ids) for index in range(c)}
        class_aggregate, class_query, class_neighborhood, baseline_aggregate, baseline_query, baseline_neighborhood = (
            _run_helper(songs, classes, _baseline_vectors(song_ids))
        )
        # Above the retained-window cap topN is a constant, so the surfaces are O(N).
        assert len(class_neighborhood) == c * n * top_n
        assert len(baseline_neighborhood) == n * top_n
        assert len(class_aggregate) == c * _RULERS * _METRICS
        assert len(baseline_aggregate) == _RULERS * _METRICS
        assert 0 < len(class_query) <= c * n * _RULERS * _METRICS
        assert 0 < len(baseline_query) <= n * _RULERS * _METRICS
        observed[n] = (
            len(class_query),
            len(class_neighborhood),
            len(baseline_query),
            len(baseline_neighborhood),
        )

    small_query, small_neighborhood, small_baseline_query, small_baseline_neighborhood = observed[101]
    large_query, large_neighborhood, large_baseline_query, large_baseline_neighborhood = observed[202]

    # N -> 2N with T fixed: every retrieval surface exactly doubles.
    assert large_query == 2 * small_query
    assert large_neighborhood == 2 * small_neighborhood
    assert large_baseline_query == 2 * small_baseline_query
    assert large_baseline_neighborhood == 2 * small_baseline_neighborhood

    # A neighbourhood surface that stored the full N x N matrix would be ~4x; it is not.
    assert large_neighborhood < 4 * small_neighborhood
    assert large_neighborhood != 202 * 202
    assert large_baseline_neighborhood != 202 * 202

    # Structural evidence is N x T: doubling N exactly doubles the stored rows.
    structural = duckdb.connect(":memory:")
    ensure_schema(structural)
    counts_101 = _write_threshold_surfaces(structural, run_id="run-struct-n101", n=101, t=4)
    counts_202 = _write_threshold_surfaces(structural, run_id="run-struct-n202", n=202, t=4)
    structural.close()
    assert counts_101["structural"] == 101 * 4
    assert counts_202["structural"] == 202 * 4
    assert counts_202["structural"] == 2 * counts_101["structural"]
    assert counts_202["structural"] != 202 * 202
    assert counts_101["class_map"] == counts_202["class_map"] == 4


def test_p2s3_class_doubling_is_linear_not_quadratic() -> None:
    n = 4
    top_n = min(n - 1, _NEIGHBORHOOD_SIZE)
    songs = _song_list(n)
    song_ids = tuple(str(song["song_id"]) for song in songs)
    baseline = _baseline_vectors(song_ids)

    def _counts(class_count: int) -> tuple[int, int, int]:
        classes = {f"class-{index}": _full_class(song_ids) for index in range(class_count)}
        aggregate, query, neighborhood, _ba, _bq, _bn = _run_helper(songs, classes, baseline)
        return len(aggregate), len(query), len(neighborhood)

    small_aggregate, small_query, small_neighborhood = _counts(2)
    large_aggregate, large_query, large_neighborhood = _counts(4)

    assert small_aggregate == 2 * _RULERS * _METRICS
    assert large_aggregate == 4 * _RULERS * _METRICS
    assert large_aggregate == 2 * small_aggregate
    assert large_query == 2 * small_query
    assert large_neighborhood == 2 * small_neighborhood
    assert small_neighborhood == 2 * n * top_n
    assert large_neighborhood == 4 * n * top_n
    assert large_neighborhood < 4 * small_neighborhood
