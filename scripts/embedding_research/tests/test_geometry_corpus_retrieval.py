"""Spec-first corpus-wide leave-one-out retrieval tests for Plan C.

These fixtures define the corrective contract before the scheduler is refactored:
two- and multi-song corpora with distinguishable self/cross-song scores, explicit
self exclusion, corpus-wide collapse identities, the same-population observed
baseline, independent rulers, non-comparable evidence, one Gram load per song for
all 171 thresholds, bounded top-N neighborhoods, and no full NxN matrix.
"""

from __future__ import annotations

from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    _NEIGHBORHOOD_SIZE,
    _alignment_ok,
    _select_neighborhood,
    analyze_geometry_corpus,
)
from scripts.embedding_research.common.threshold_analysis import (
    AllThresholdAnalysis,
    SearchRepresentation,
    StructuralIdentity,
    ThresholdAnalysisResult,
    ThresholdSpec,
    collapse_search_representations,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.helpers.corpus_identity import (
    CorpusSongSearchInput,
    search_representation_id,
    structural_identity,
)

pytestmark = pytest.mark.unit

# Candidate-side scores (independent of the query).  A song is never its own candidate.
_CAND_SCORE = {"song-1": 0.40, "song-2": 0.90, "song-3": 0.20}
_BASELINE_FACTOR = 0.5

_STREAMS = {
    "song-1": [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
    "song-2": [[0.0, 1.0], [1.0, 0.0], [1.0, 0.0]],
    "song-3": [[1.0, 1.0], [1.0, 0.0], [0.0, 1.0]],
}


class _Identity:
    def __init__(self, song_id: str, backbone: str, commit: str, mask_digest: str) -> None:
        self.song_id = song_id
        self.backbone = backbone
        self.mask_ref = f"mask-ref:{song_id}"
        self.mask_digest = mask_digest
        self.alignment_token = f"align:{song_id}"
        self.audio_content_sha256 = f"audio:{song_id}"
        self.mask_semantics_version = "mask-v1"
        self.group_format_version = "group-v1"
        self.observation_group_sha256 = commit
        self.commit_sha256 = commit


class _StreamRecord:
    def __init__(self, patch_count: int, embedding_dim: int) -> None:
        self.stream_ref = "stream-ref"
        self.fingerprint_sha256 = "stream-fingerprint"
        self.stream_payload_sha256 = "stream-payload"
        self.patch_count = patch_count
        self.embedding_dim = embedding_dim
        self.stream_dtype = "float32"
        self.stream_format_version = "stream-v1"
        self.embed_semantics_version = 1
        self.preprocess_fn = "preprocess"
        self.preprocess_version = "1"
        self.backbone_model_hash = "model"
        self.audio_params = "synthetic"
        self.provenance_source = "synthetic"
        self.provenance_assumption = "fixture"


class _Observation:
    def __init__(self, con, song_id: str, stream: list[list[float]], mask: np.ndarray | None = None) -> None:
        self.con = con
        self.identity = _Identity(song_id, "effnet", f"commit:{song_id}", f"mask:{song_id}")
        self.stream = np.asarray(stream, dtype=np.float32)
        self.stream_record = _StreamRecord(self.stream.shape[0], self.stream.shape[1])
        self.mask = np.ones(self.stream.shape[0], dtype=np.uint8) if mask is None else mask
        self.provenance_identity = f"provenance:{song_id}"


class _Store:
    def __init__(self, observations: dict[str, _Observation]) -> None:
        self.observations = observations
        self.loads = 0
        self.gathers: list[tuple[str, tuple[int, ...]]] = []

    def load_committed_observation(self, song_id: str, backbone: str) -> _Observation:
        assert backbone == "effnet"
        self.loads += 1
        return self.observations[song_id]

    def batch_gather(self, song_id: str, backbone: str, indices, *, forbid_duplicates: bool) -> np.ndarray:
        assert backbone == "effnet"
        assert forbid_duplicates is True
        values = tuple(int(index) for index in indices)
        self.gathers.append((song_id, values))
        return np.asarray(self.observations[song_id].stream[list(values)], dtype=np.float32)


def _scorer(records: list[tuple[int, str, float, int]]) -> object:
    def score(query, _weights, candidate):  # type: ignore[no-untyped-def]
        candidate_song = str(candidate.row_addresses[0][1])
        factor = 1.0 if len(query) > 1 else _BASELINE_FACTOR
        value = _CAND_SCORE[candidate_song] * factor
        records.append((id(query), candidate_song, value, len(query)))
        return SimpleNamespace(finite=True, score=value)

    return score


def _corpus(con, songs: list[dict[str, object]]):
    observations: dict[str, _Observation] = {}
    records = {}
    for spec in songs:
        song_id = str(spec["song_id"])
        observation = _Observation(con, song_id, spec["stream"], spec.get("mask"))  # type: ignore[arg-type]
        observations[song_id] = observation
        records[song_id] = write_geometry(observation, GeometryProfile.current(), f"seed:{song_id}")

    from scripts.embedding_research.common.geometry_analysis import GeometryCorpusRequest, GeometrySongRequest

    profile = GeometryProfile.current()
    items = []
    for spec in songs:
        song_id = str(spec["song_id"])
        record = records[song_id]
        items.append(
            GeometrySongRequest(
                song_id,
                "effnet",
                GeometryIdentity(
                    song_id,
                    "effnet",
                    f"commit:{song_id}",
                    record.identity.geometry_semantics_version,
                    record.identity.numerical_profile_digest,
                ),
                dict(record.evidence),
                artist=spec.get("artist"),  # type: ignore[arg-type]
                genre=spec.get("genre"),  # type: ignore[arg-type]
                head_label=spec.get("head_label"),
            )
        )
    request = GeometryCorpusRequest(
        items=tuple(items),
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        scoring_semantics_version=1,
        run_id="run-a",
        execution_id="execution-a",
        numerical_profile_digest=profile.digest,
    )
    return request, _Store(observations)


def _songs() -> list[dict[str, object]]:
    return [
        {"song_id": "song-1", "stream": _STREAMS["song-1"], "artist": "art", "genre": "rock", "head_label": ("h1",)},
        {"song_id": "song-2", "stream": _STREAMS["song-2"], "artist": "art", "genre": None, "head_label": None},
        {"song_id": "song-3", "stream": _STREAMS["song-3"], "artist": None, "genre": "rock", "head_label": ("h1",)},
    ]


def test_leave_one_out_scores_every_other_song_and_never_self() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    records: list[tuple[int, str, float, int]] = []
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer(records)
    )

    # Every published threshold has complete leave-one-out evidence. Scorer work
    # may be cached by equal collapse class, so call-order cardinality is not
    # expected to equal the publication cardinality.
    comparable_queries = [query for query in result.queries if query.state.comparable]
    assert len(comparable_queries) == len(
        {(query.collapse_class_id, query.threshold_id, query.request.song_id) for query in comparable_queries}
    )
    for query in comparable_queries:
        own = query.request.song_id
        candidate_ids = [entry.song_id for entry in query.neighborhood]
        assert candidate_ids
        assert own not in candidate_ids
        assert len(candidate_ids) == len(set(candidate_ids))
    assert len(records) == result.counters.scorer_call_count

    for query in result.queries:
        own = query.request.song_id
        assert query.neighborhood
        assert all(entry.song_id != own for entry in query.neighborhood)
        assert all(entry.song_id != own for entry in query.baseline_neighborhood)
        assert query.scores.scores
        assert query.scores.evaluation_comparable is True
        assert query.state.comparable is True

    # Distinguishable cross-song scores: max candidate score determines the winner.
    assert len(
        {(query.collapse_class_id, query.threshold_id, query.request.song_id) for query in result.queries}
    ) == len(result.queries)
    con.close()


def test_corpus_wide_collapse_is_threshold_independent_and_mixed_identity_safe() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    # A constant stream makes every threshold produce the same segmentation/medoid;
    # only the excluded structural identity differs, so all 171 collapse to one.
    songs = [
        {"song_id": "song-1", "stream": [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]},
        {"song_id": "song-2", "stream": _STREAMS["song-2"]},
    ]
    request, store = _corpus(con, songs)
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )

    song_one = [candidate for candidate in result.candidates if candidate.representation.song_id == "song-1"]
    assert len(song_one) == len({candidate.representation.search_representation_id for candidate in song_one})
    assert {index for candidate in song_one for index in candidate.threshold_indices} == set(range(171))
    # Structural identity is retained separately and never feeds the search identity.
    assert song_one[0].structural_identity
    assert song_one[0].representation.search_representation_id != song_one[0].structural_identity
    assert song_one[0].representation.source_indices == (0,)
    con.close()


def test_distinguishable_thresholds_publish_independent_complete_evidence() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )

    # Each requested threshold is published, even when scorer work is reused for
    # an equal collapse class.  Threshold identity and same-T rosters remain distinct.
    assert len(result.threshold_queries) == len(request.items) * len(request.threshold_request.indices)
    by_threshold = {query.threshold_id for query in result.threshold_queries}
    assert len(by_threshold) == len(request.threshold_request.indices)
    assert {query.threshold_id for query in result.threshold_queries[:3]} == {"0"}
    first, second = result.threshold_queries[0], result.threshold_queries[3]
    assert first.threshold_id != second.threshold_id
    assert first.request.song_id == second.request.song_id
    assert first.collapse_class_id != second.collapse_class_id or first.threshold_id != second.threshold_id
    for query in result.threshold_queries:
        candidate_ids = [entry.song_id for entry in query.neighborhood]
        assert query.request.song_id not in candidate_ids
        assert len(candidate_ids) == len(set(candidate_ids))
    con.close()


def test_same_population_baseline_and_independent_rulers() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )

    for query in result.queries:
        winner_population = {entry.song_id for entry in query.neighborhood}
        baseline_population = {entry.song_id for entry in query.baseline_neighborhood}
        assert winner_population == baseline_population, "baseline must share the winner candidate population"
        assert query.scores.baseline_score is not None
        assert max(query.scores.scores.values()) >= query.scores.baseline_score

    # artist ruler covers song-1/song-2, genre covers song-1/song-3, head covers song-1/song-3.
    assert result.artist_metrics["n_songs"] >= 2.0
    assert result.genre_metrics["n_songs"] >= 2.0
    assert result.head_metrics["n_songs"] >= 2.0
    by_song = {query.request.song_id: query for query in result.queries}
    assert by_song["song-1"].state.eligible is True
    assert by_song["song-2"].state.eligible is True
    con.close()


def test_zero_searchable_is_explicitly_non_comparable() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    songs = [
        {"song_id": "song-1", "stream": _STREAMS["song-1"], "mask": np.zeros(3, dtype=np.uint8)},
        {"song_id": "song-2", "stream": _STREAMS["song-2"]},
    ]
    request, store = _corpus(con, songs)
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )

    assert all(candidate.representation.song_id != "song-1" for candidate in result.candidates)
    assert result.noncomparable
    assert all(evidence.song_id == "song-1" for evidence in result.noncomparable)
    assert any("zero_searchable" in evidence.reasons for evidence in result.noncomparable)
    disabled = next(query for query in result.queries if query.request.song_id == "song-1")
    assert disabled.state.comparable is False
    assert disabled.state.reasons
    assert disabled.neighborhood == ()
    con.close()


def test_one_gram_load_per_song_for_all_171_thresholds() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )

    assert result.counters.geometry_load_count == 3
    assert result.counters.observation_load_count == 3
    assert result.counters.threshold_analysis_count == 3
    assert result.counters.segmentation_from_scorer_count == 0
    for analysis in result.analyses:
        assert analysis.geometry_decode_count == 1
        assert len(analysis.results) == 171
    con.close()


def test_no_full_matrix_and_bounded_top_n() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    records: list[tuple[int, str, float, int]] = []
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer(records)
    )

    # Equal collapse classes reuse scorer work; publication still has complete
    # per-threshold queries, so scorer calls are bounded by unique class/song work.
    assert result.counters.scorer_call_count == len(records)
    assert result.counters.scorer_call_count < len(result.queries) * 2
    for query in result.queries:
        assert len(query.neighborhood) <= _NEIGHBORHOOD_SIZE
        ranks = [entry.rank for entry in query.neighborhood]
        assert ranks == list(range(len(query.neighborhood)))
    assert _NEIGHBORHOOD_SIZE >= 100

    # The bounded selector caps a large synthetic population deterministically.
    from scripts.embedding_research.common.geometry_analysis import FrozenSearchRepresentation

    def _rep(i: int) -> FrozenSearchRepresentation:
        return FrozenSearchRepresentation(
            song_id=f"s{i:03d}",
            backbone="effnet",
            source_indices=(0,),
            vectors=np.asarray([[1.0, 0.0]], dtype=np.float32),
            weights=np.ones(1, dtype=np.float64),
            search_representation_id=f"rep-{i:03d}",
            geometry_id=f"g{i}",
            observation_group_sha256=f"o{i}",
            numerical_profile_digest="p",
            mask_digest="m",
            scoring_semantics_version=1,
            experiment="temporal_global",
        )

    lookup = {f"rep-{i:03d}": _rep(i) for i in range(150)}
    scores = {key: float(i) for i, key in enumerate(lookup)}
    neighborhood = _select_neighborhood(scores, lookup)
    assert len(neighborhood) == _NEIGHBORHOOD_SIZE
    assert [entry.rank for entry in neighborhood] == list(range(_NEIGHBORHOOD_SIZE))
    assert [entry.score for entry in neighborhood] == sorted(scores.values(), reverse=True)[:_NEIGHBORHOOD_SIZE]
    con.close()


def test_search_identity_is_geometry_independent_and_structurally_separate() -> None:
    base = {
        "experiment": "temporal_global",
        "scoring_semantics_version": 1,
        "geometry_semantics_version": "gram-v1",
        "numerical_profile_digest": "a" * 64,
        "ordered_song_inputs": (
            CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0, 2), (0.5, 0.5), 3),
            CorpusSongSearchInput("s2", "b" * 64, "c" * 64, (0, 2), (0.5, 0.5), 3),
        ),
    }
    first = search_representation_id(**base)
    assert first == search_representation_id(**base)
    assert (
        search_representation_id(
            **{
                **base,
                "ordered_song_inputs": (
                    base["ordered_song_inputs"][0],
                    CorpusSongSearchInput("s2", "d" * 64, "c" * 64, (0, 2), (0.5, 0.5), 3),
                ),
            }
        )
        != first
    )
    assert (
        search_representation_id(**{**base, "ordered_song_inputs": tuple(reversed(base["ordered_song_inputs"]))})
        != first
    )
    structural = structural_identity(threshold_id="t0", boundaries=((0, 1),), absorbed_locations=())
    assert structural != first


def test_alignment_failure_is_rejected() -> None:
    assert _alignment_ok((0,), (0.0,)) is False
    assert _alignment_ok((), ()) is False
    assert _alignment_ok((0, 1), (0.5, 0.5)) is True


@pytest.mark.unit
def test_threshold_hypotheses_are_t_derived_unique_and_neighborhoods_deduplicate_songs() -> None:
    """Adversarially pin threshold-specific representations and candidate identity."""
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    calls: list[tuple[int, str, float, int]] = []
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer(calls)
    )
    assert len(result.hypotheses) == 171
    assert len(result.queries) == len(
        {(query.collapse_class_id, query.threshold_id, query.request.song_id) for query in result.queries}
    )
    assert all(
        len({entry.song_id for entry in query.neighborhood}) == len(query.neighborhood) for query in result.queries
    )
    assert all(
        len({entry.song_id for entry in query.baseline_neighborhood}) == len(query.baseline_neighborhood)
        for query in result.queries
    )
    assert all(query.request.song_id not in {entry.song_id for entry in query.neighborhood} for query in result.queries)
    assert all(
        query.request.song_id not in {entry.song_id for entry in query.baseline_neighborhood}
        for query in result.queries
    )
    con.close()


@pytest.mark.unit
def test_search_hash_changes_for_complete_ordered_scoring_input_but_not_threshold_or_structure() -> None:
    base = {
        "experiment": "temporal_global",
        "scoring_semantics_version": 1,
        "geometry_semantics_version": "gram-v1",
        "numerical_profile_digest": "a" * 64,
        "ordered_song_inputs": (
            CorpusSongSearchInput("s1", "b" * 64, "c" * 64, (0, 2), (0.5, 0.5), 3),
            CorpusSongSearchInput("s2", "b" * 64, "c" * 64, (0, 2), (0.5, 0.5), 3),
        ),
    }
    first = search_representation_id(**base)
    changed = CorpusSongSearchInput("s2", "b" * 64, "c" * 64, (0, 2), (0.5, 0.5), 4)
    assert (
        search_representation_id(**{**base, "ordered_song_inputs": (base["ordered_song_inputs"][0], changed)}) != first
    )
    changed = CorpusSongSearchInput("s2", "b" * 64, "c" * 64, (0, 2), (0.25, 0.75), 3)
    assert (
        search_representation_id(**{**base, "ordered_song_inputs": (base["ordered_song_inputs"][0], changed)}) != first
    )
    assert search_representation_id(**base) == first
    assert structural_identity(threshold_id="T2", boundaries=((0, 2),), absorbed_locations=()) != first


@pytest.mark.unit
def test_complete_corpus_mutation_blocks_threshold_collapse_but_identity_axes_do_not() -> None:
    """Collapse compares every ordered song input, not only the query song."""
    base_inputs = (
        CorpusSongSearchInput("song-1", "obs-1", "mask-1", (0,), (1.0,), 1),
        CorpusSongSearchInput("song-2", "obs-2", "mask-2", (1, 2), (0.25, 0.75), 4),
    )
    base = search_representation_id(
        experiment="temporal_global",
        scoring_semantics_version=1,
        geometry_semantics_version="gram-v1",
        numerical_profile_digest="a" * 64,
        ordered_song_inputs=base_inputs,
    )
    mutated = search_representation_id(
        experiment="temporal_global",
        scoring_semantics_version=1,
        geometry_semantics_version="gram-v1",
        numerical_profile_digest="a" * 64,
        ordered_song_inputs=(
            base_inputs[0],
            CorpusSongSearchInput("song-2", "obs-2", "mask-2", (3, 2), (0.5, 0.5), 5),
        ),
    )
    assert mutated != base
    search_t1 = SearchRepresentation(
        "struct-t1", (0,), (1.0,), 1, "geometry", "obs", "profile", "mask", 1, "temporal_global", base
    )
    search_t2 = SearchRepresentation(
        "struct-t2", (3, 2), (0.5, 0.5), 5, "geometry", "obs", "profile", "mask", 1, "temporal_global", mutated
    )
    analysis = AllThresholdAnalysis(
        "temporal_global",
        "geometry",
        "obs",
        "profile",
        "mask",
        (
            ThresholdAnalysisResult(
                ThresholdSpec(1, 0.31, "T1"), StructuralIdentity("T1", 1, ((0, 1),), (), "struct-t1"), search_t1, None
            ),
            ThresholdAnalysisResult(
                ThresholdSpec(2, 0.32, "T2"), StructuralIdentity("T2", 2, ((0, 2),), (), "struct-t2"), search_t2, None
            ),
        ),
        "gram-v1",
        "evaluation",
        "execution",
    )
    assert len(collapse_search_representations(analysis)) == 2
    # Threshold and structural identities are separate evidence axes.
    assert (
        search_representation_id(
            experiment="temporal_global",
            scoring_semantics_version=1,
            geometry_semantics_version="gram-v1",
            numerical_profile_digest="a" * 64,
            ordered_song_inputs=base_inputs,
        )
        == base
    )
    assert structural_identity(threshold_id="T2", boundaries=((0, 3),), absorbed_locations=((1,),)) != base


@pytest.mark.unit
def test_winner_and_global_baseline_rosters_use_distinct_vectors() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    request, store = _corpus(con, _songs())
    result = analyze_geometry_corpus(
        request, con=con, stream_store=store, profile=GeometryProfile.current(), scoring=_scorer([])
    )
    baseline = result.baseline
    assert baseline is not None and baseline.is_observed_baseline
    winner_ids = {id(candidate.representation) for candidate in result.candidates}
    assert id(baseline) not in winner_ids
    assert {candidate.representation.song_id for candidate in result.candidates} == {"song-1", "song-2", "song-3"}
    assert baseline.source_indices
    con.close()
