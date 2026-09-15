"""Plan C Phase 1 — end-to-end adversarial matrix (A-M) coverage proof.

This module holds ONLY end-to-end cases that must cross the real production chain:

    ``run.py::_run_analyze``
        -> ``common/geometry_analysis.py::build_geometry_corpus_request``
        -> ``common/geometry_analysis.py::analyze_geometry_corpus``
        -> ``common/geometry_analysis.py::write_geometry_corpus_analysis``
        -> ``report/__init__.py::run``

against an in-memory DuckDB with explicit synthetic stream/geometry/mask doubles.
The only patched seams are the two disk-backed stream-store constructors and the
synthetic-only flag, so no real corpus, model, audio, ONNX, or CUDA is touched.

It also asserts that the mandatory adversarial matrix A-M is enumerated and every
letter is owned by an existing, uniquely-assigned test (no gaps, no duplicate intent).
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import run as run_module
from scripts.embedding_research.common import geometry_analysis
from scripts.embedding_research.common.threshold_analysis import dense_primary_threshold_request
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.songs import upsert_song
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.report._retrieval import collect_report_frames
from scripts.embedding_research.streams import store as stream_store_module

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RUN_ID = "run-adversarial-matrix"
_EXECUTION_ID = f"execution:{_RUN_ID}:{_BACKBONE}"
_STREAMS = {
    "song-1": [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
    "song-2": [[0.0, 1.0], [1.0, 0.0], [0.0, -1.0]],
    "song-3": [[1.0, 0.0], [0.0, -1.0], [-1.0, 0.0]],
}
_LABELS = {
    "song-1": ("art", "rock"),
    "song-2": ("art", "rock"),
    "song-3": ("other", "jazz"),
}

_TESTS_DIR = Path(__file__).resolve().parent
_RS = "test_experiment_one_result_surfaces.py"
_TCM = "test_experiment_one_threshold_class_map.py"
_CM = "test_experiment_one_class_metrics.py"
_RB = "test_experiment_one_result_readback.py"
_HL = "test_experiment_one_head_labels.py"
_RC = "test_experiment_one_report_curves.py"
_HC = "test_experiment_one_hard_cut.py"
_SELF = "test_experiment_one_adversarial_matrix.py"

# Mandatory adversarial matrix A-M -> owning test file(s) -> owning test function(s).
_MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
    "A": {
        _RS: ("test_a_normalized_surfaces_write_no_duplicate_identity_over_171_thresholds",),
        _TCM: ("test_a_171_threshold_publication_is_one_map_row_per_threshold_and_linear_structural",),
    },
    "B": {
        _CM: ("test_b_artist_first_and_non_artist_first_classes_diverge",),
        _RB: ("test_readback_retains_t1_t2_metric_distinction",),
        _SELF: ("test_e2e_t1_t2_divergence_read_back_through_analyze_and_report",),
    },
    "C": {
        _CM: (
            "test_c_identical_class_inputs_collapse_to_identical_metrics_and_neighborhoods",
            "test_c_owner_collapses_equal_thresholds_into_one_retrieval_source",
        ),
        _RS: ("test_c_equal_threshold_inputs_collapse_to_one_class_and_read_back",),
        _RB: ("test_readback_retains_two_thresholds_sharing_one_class",),
    },
    "D": {_CM: ("test_d_mutating_one_song_representation_prevents_collapse",)},
    "E": {_RS: ("test_e_non_comparable_class_emits_no_partial_metrics_but_baseline_covers_corpus",)},
    "F": {_CM: ("test_f_baseline_same_artist_candidate_relevant_by_song_identity",)},
    "G": {
        _HL: (
            "test_frozen_activations_not_suite_names_drive_the_head_label",
            "test_missing_head_evidence_excludes_only_the_head_ruler",
        )
    },
    "H": {_CM: ("test_h_first_relevant_beyond_retained_bound_uses_complete_ranking_rank",)},
    "I": {
        _RS: ("test_i_baseline_counts_are_independent_of_threshold_count",),
        _SELF: ("test_e2e_single_threshold_independent_baseline",),
    },
    "J": {
        _RS: ("test_j_same_query_candidate_under_two_classes_round_trips_distinctly",),
        _SELF: ("test_e2e_cross_class_pair_distinctness",),
    },
    "K": {_RS: ("test_k_per_query_metrics_cover_artist_genre_and_head_with_status",)},
    "L": {_RC: ("test_report_payload_has_two_threshold_points_and_one_fixed_baseline",)},
    "M": {
        _HC: (
            "test_active_code_has_no_retired_nested_result_symbol",
            "test_schema_creates_no_retired_metric_table",
        )
    },
}


def _test_functions(filename: str) -> set[str]:
    tree = ast.parse((_TESTS_DIR / filename).read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")}


def test_adversarial_matrix_a_to_m_has_no_gaps_or_duplicate_intent() -> None:
    assert set(_MATRIX) == set("ABCDEFGHIJKLM")
    owners: dict[str, str] = {}
    for letter, by_file in _MATRIX.items():
        assert by_file, f"letter {letter} has no owning test file"
        for filename, names in by_file.items():
            assert names, f"letter {letter}/{filename} names no test"
            present = _test_functions(filename)
            for name in names:
                assert name in present, f"letter {letter}: {filename}::{name} is missing"
                previous = owners.setdefault(name, letter)
                assert previous == letter, f"{name} claims both {previous} and {letter}"


# ---------------------------------------------------------------------------
# End-to-end fixture: one real analyze -> write -> report run over synthetic doubles
# ---------------------------------------------------------------------------


def _make_observation(song_id: str, con) -> object:
    group = f"group-{song_id}"
    identity = SimpleNamespace(
        song_id=song_id,
        backbone=_BACKBONE,
        observation_group_sha256=group,
        commit_sha256=group,
        mask_ref="mask-ref",
        mask_digest="mask-a",
        alignment_token="align",
        audio_content_sha256=f"audio-{song_id}",
        mask_semantics_version="mask-v1",
        group_format_version="group-v1",
        patch_count=3,
    )
    stream_record = SimpleNamespace(
        stream_ref="stream-ref",
        fingerprint_sha256=f"stream-fingerprint-{song_id}",
        stream_payload_sha256=f"stream-payload-{song_id}",
        patch_count=3,
        embedding_dim=2,
        stream_dtype="float32",
        stream_format_version="stream-v1",
        embed_semantics_version=1,
        preprocess_fn="preprocess",
        preprocess_version="1",
        backbone_model_hash="model",
        audio_params="synthetic",
        provenance_source="synthetic",
        provenance_assumption="fixture",
    )
    return SimpleNamespace(
        con=con,
        identity=identity,
        stream_record=stream_record,
        provenance_identity="provenance",
        mask=np.ones(3, dtype=np.uint8),
        stream=np.asarray(_STREAMS[song_id], dtype=np.float32),
    )


def _head_store_factory(_con, *, output_root=None):
    return SimpleNamespace(output_root=output_root)


class _SyntheticStore:
    """In-memory stream-store double; never touches audio, disk, or a model."""

    def __init__(self, con, *, output_root=None) -> None:
        self.con = con
        self.output_root = output_root
        self.observations = {song_id: _make_observation(song_id, con) for song_id in _STREAMS}

    def load_committed_observation(self, song_id, backbone):
        assert backbone == _BACKBONE
        return self.observations[song_id]

    def batch_gather(self, song_id, backbone, indices, *, forbid_duplicates):
        assert forbid_duplicates is True
        assert backbone == _BACKBONE
        return np.asarray(self.observations[song_id].stream[list(indices)], dtype=np.float32)


def _seed_corpus(con) -> None:
    for song_id, (artist, genre) in _LABELS.items():
        upsert_song(
            con,
            song_id=song_id,
            path=f"/synthetic/{song_id}.flac",
            artist=artist,
            album="album",
            title=song_id,
            genre=genre,
        )
        write_geometry(_make_observation(song_id, con), GeometryProfile.current(), _RUN_ID)


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    runtime_root = tmp_path_factory.mktemp("runtime")
    out_path = tmp_path_factory.mktemp("report")
    html_path = tmp_path_factory.mktemp("viewer") / "viewer.html"
    created: list[_SyntheticStore] = []

    def _store_factory(con, *, output_root=None):
        store = _SyntheticStore(con, output_root=output_root)
        created.append(store)
        return store

    real_build = geometry_analysis.build_geometry_corpus_request

    def _synthetic_build(*args, **kwargs):
        kwargs["synthetic_only"] = True
        return real_build(*args, **kwargs)

    with (
        mock.patch.object(stream_store_module, "StreamStore", _store_factory),
        mock.patch.object(stream_store_module, "HeadStreamStore", _head_store_factory),
        mock.patch.object(geometry_analysis, "build_geometry_corpus_request", _synthetic_build),
    ):
        con = duckdb.connect(":memory:")
        ensure_schema(con)
        _seed_corpus(con)
        run_module._run_analyze(
            con,
            {
                "threshold_request": dense_primary_threshold_request(),
                "experiment": "temporal_global",
                "backbones": [_BACKBONE],
                "runtime_root": runtime_root,
                "song_ids": None,
            },
            _RUN_ID,
        )
        store = created[0]
        frames = collect_report_frames(con, run_id=_RUN_ID)
        payload = report_run(
            con,
            out_path,
            run_id=_RUN_ID,
            stream_store=store,
            profile=GeometryProfile.current(),
            html_out_path=html_path,
        )

    yield SimpleNamespace(con=con, frames=frames, payload=payload, store=store)
    con.close()


def _section(payload: dict, section_id: str) -> dict:
    return next(section for section in payload["sections"] if section["id"] == section_id)


def _table(section: dict, table_id: str) -> dict:
    return next(table for table in section["tables"] if table["id"] == table_id)


def _rows(table: dict) -> list[dict[str, str]]:
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


def test_e2e_t1_t2_divergence_read_back_through_analyze_and_report(e2e) -> None:
    frames = e2e.frames
    class_map = frames.threshold_class_map
    assert len(class_map) == 171
    # Every analyze fixture in this matrix is single-backbone-consistent.
    assert {row["execution_id"] for row in class_map} == {_EXECUTION_ID}

    class_by_threshold = {row["threshold_id"]: row["corpus_search_class_id"] for row in class_map}
    assert len(set(class_by_threshold.values())) >= 2
    artist_mrr = {
        row["corpus_search_class_id"]: row["value"]
        for row in frames.class_aggregate_metrics
        if row["ruler"] == "artist" and row["metric"] == "mrr"
    }

    pair = None
    thresholds = list(class_by_threshold.items())
    for t1, c1 in thresholds:
        for t2, c2 in thresholds:
            if c1 != c2 and artist_mrr.get(c1) != artist_mrr.get(c2):
                pair = (t1, c1, t2, c2)
                break
        if pair is not None:
            break
    assert pair is not None, "no two thresholds produce distinct class-scoped artist metrics"
    t1, c1, t2, c2 = pair

    # Divergence survives the report read path: threshold -> class -> metric.
    curve = _rows(_table(_section(e2e.payload, "analysis"), "geometry_threshold_map"))
    curve_class = {row["threshold_id"]: row["corpus_search_class_id"] for row in curve}
    assert curve_class[t1] == c1 and curve_class[t2] == c2
    curve_values: dict[tuple[str, str, str], float] = {}
    for row in curve:
        curve_values[(row["threshold_id"], row["ruler"], row["metric"])] = float(row["class_value"])
    shared_axes = {key[1:] for key in curve_values if key[0] == t1} & {key[1:] for key in curve_values if key[0] == t2}
    assert any(curve_values[(t1, *axis)] != curve_values[(t2, *axis)] for axis in shared_axes)


def test_e2e_single_threshold_independent_baseline(e2e) -> None:
    frames = e2e.frames
    baseline = frames.baseline_aggregate_metrics
    assert len(baseline) == 3 * 5
    assert {row["backbone"] for row in baseline} == {_BACKBONE}
    assert len({(row["ruler"], row["metric"], row["k"]) for row in baseline}) == len(baseline) == 15

    baseline_query = frames.baseline_query_metrics
    assert len({(row["query_song_id"], row["ruler"], row["metric"], row["k"]) for row in baseline_query}) == len(
        baseline_query
    )

    provenance = frames.provenance
    assert provenance["synthetic_only"] is True
    assert provenance["evidence_mode"] == "synthetic_fixture"

    # The rendered payload carries exactly ONE fixed threshold-independent baseline block.
    summary_rows = _rows(_table(_section(e2e.payload, "summary"), "observed_baseline_summary"))
    assert len(summary_rows) == 1


def test_e2e_cross_class_pair_distinctness(e2e) -> None:
    frames = e2e.frames
    pairs_by_class: dict[tuple[str, str], set[str]] = {}
    for row in frames.class_neighborhoods:
        pairs_by_class.setdefault((row["query_song_id"], row["candidate_song_id"]), set()).add(
            row["corpus_search_class_id"]
        )
    multi = {pair: classes for pair, classes in pairs_by_class.items() if len(classes) >= 2}
    assert multi, "no (query, candidate) pair is retained under two classes"

    rendered = _rows(_table(_section(e2e.payload, "winners"), "geometry_representations"))
    rendered_keys = {
        (row["query_song_id"], row["candidate_song_id"], row["corpus_search_class_id"]) for row in rendered
    }
    some_pair, some_classes = next(iter(multi.items()))
    for class_id in some_classes:
        assert (*some_pair, class_id) in rendered_keys
