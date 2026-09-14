"""Bounded real-caller integration for the Experiment One normalized result layer.

Exercises the REAL production chain end to end:

    ``run.py::_run_analyze``
        -> ``common/geometry_analysis.py::build_geometry_corpus_request``
        -> ``common/geometry_analysis.py::analyze_geometry_corpus``
        -> ``common/geometry_analysis.py::write_geometry_corpus_analysis``
        -> ``report/__init__.py::run``

against an in-memory DuckDB and explicit synthetic stream/geometry/mask doubles. The only
seam patched is the two disk-backed stream-store constructors (replaced by in-memory doubles)
and the synthetic-only flag; the analysis, persistence, and report code paths are the real
ones. No real corpus, model, audio, ONNX, or CUDA execution occurs.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import run as run_module
from scripts.embedding_research.common import geometry_analysis
from scripts.embedding_research.common.geometry_analysis import write_geometry_corpus_analysis  # noqa: F401
from scripts.embedding_research.common.threshold_analysis import dense_primary_threshold_request
from scripts.embedding_research.config import OUTPUT_ROOT
from scripts.embedding_research.db import ensure_schema, write_geometry
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.db.result_surfaces import (
    read_baseline_neighborhoods,
    read_result_provenance,
)
from scripts.embedding_research.db.songs import upsert_song
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.report._retrieval import collect_report_frames
from scripts.embedding_research.streams import store as stream_store_module

pytestmark = pytest.mark.unit

_BACKBONE = "effnet"
_RUN_ID = "run-result-layer-real-caller"
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
    """Synthetic head store; the forced synthetic-only path never resolves real activations."""
    return SimpleNamespace(output_root=output_root)


class _SyntheticStore:
    """In-memory stream-store double; never touches audio, disk, or a model."""

    def __init__(self, con, *, output_root=None) -> None:
        self.con = con
        self.output_root = output_root
        self.observations = {song_id: _make_observation(song_id, con) for song_id in _STREAMS}
        self.load_count = 0
        self.gather_count = 0

    def load_committed_observation(self, song_id, backbone):
        assert backbone == _BACKBONE
        self.load_count += 1
        return self.observations[song_id]

    def batch_gather(self, song_id, backbone, indices, *, forbid_duplicates):
        assert forbid_duplicates is True
        assert backbone == _BACKBONE
        self.gather_count += 1
        return np.asarray(self.observations[song_id].stream[list(indices)], dtype=np.float32)


def _output_root_snapshot() -> frozenset[str]:
    if not OUTPUT_ROOT.exists():
        return frozenset()
    return frozenset(str(path) for path in OUTPUT_ROOT.rglob("*"))


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
        observation = _make_observation(song_id, con)
        write_geometry(observation, GeometryProfile.current(), _RUN_ID)


def test_real_analyze_to_report_path_over_synthetic_doubles(tmp_path, monkeypatch) -> None:
    created_stores: list[_SyntheticStore] = []

    def _store_factory(con, *, output_root=None):
        store = _SyntheticStore(con, output_root=output_root)
        created_stores.append(store)
        return store

    monkeypatch.setattr(stream_store_module, "StreamStore", _store_factory)
    monkeypatch.setattr(stream_store_module, "HeadStreamStore", _head_store_factory)

    # The real caller passes synthetic_only=False (empirical request); this bounded integration
    # forces the synthetic-only branch so build_geometry_corpus_request never resolves real head
    # activations. Record the forced flag for the absence assertion below.
    real_build = geometry_analysis.build_geometry_corpus_request
    synthetic_flags: list[bool] = []

    def _synthetic_build(*args, **kwargs):
        kwargs["synthetic_only"] = True
        synthetic_flags.append(True)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(geometry_analysis, "build_geometry_corpus_request", _synthetic_build)

    output_root_before = _output_root_snapshot()
    modules_before = set(sys.modules)

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _seed_corpus(con)

    runtime_root = tmp_path / "runtime"
    cfg = {
        "threshold_request": dense_primary_threshold_request(),
        "experiment": "temporal_global",
        "backbones": [_BACKBONE],
        "runtime_root": runtime_root,
        "song_ids": None,
    }

    # 1. The real run.py::_run_analyze chain (build -> analyze -> write).
    summary = run_module._run_analyze(con, cfg, _RUN_ID)
    assert summary["song_count"] == 3
    assert created_stores, "the real caller must construct a stream store"
    store = created_stores[0]
    assert isinstance(store, _SyntheticStore)
    assert store.load_count > 0
    assert store.gather_count > 0
    assert synthetic_flags == [True]

    # 2. The normalized surfaces are exactly what the writer persisted.
    frames = collect_report_frames(con, run_id=_RUN_ID)
    assert len(frames.threshold_class_map) == 171
    assert frames.provenance["synthetic_only"] is True
    assert frames.provenance["evidence_mode"] == "synthetic_fixture"
    assert frames.baseline_aggregate_metrics
    assert frames.baseline_neighborhoods
    assert frames.class_aggregate_metrics

    # 3. The real report read path renders the full seven-section schema-v2 report.
    out_path = tmp_path / "report"
    html_path = tmp_path / "viewer.html"
    payload = report_run(
        con,
        out_path,
        run_id=_RUN_ID,
        stream_store=store,
        profile=GeometryProfile.current(),
        html_out_path=html_path,
    )
    assert payload["schema_version"] == 2
    assert [section["id"] for section in payload["sections"]] == [
        "summary",
        "corpus",
        "analysis",
        "winners",
        "head-analysis",
        "provenance",
        "efficiency",
    ]
    assert (out_path / "report.json").exists()
    assert html_path.exists()

    # 4. Absence proof: no real corpus/model/audio/ONNX/CUDA execution.
    assert created_stores == [store]  # only the in-memory double was ever constructed
    assert not [name for name in set(sys.modules) - modules_before if name.startswith(("onnxruntime", "torch"))]
    assert _output_root_snapshot() == output_root_before


def test_real_analyze_persists_distinct_class_scoped_rows(tmp_path, monkeypatch) -> None:
    """The real caller persists per-class retrieval rows, not one global lookup."""

    def _store_factory(con, *, output_root=None):
        return _SyntheticStore(con, output_root=output_root)

    monkeypatch.setattr(stream_store_module, "StreamStore", _store_factory)
    monkeypatch.setattr(stream_store_module, "HeadStreamStore", _head_store_factory)
    real_build = geometry_analysis.build_geometry_corpus_request

    def _synthetic_build(*args, **kwargs):
        kwargs["synthetic_only"] = True
        return real_build(*args, **kwargs)

    monkeypatch.setattr(geometry_analysis, "build_geometry_corpus_request", _synthetic_build)

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _seed_corpus(con)
    runtime_root = tmp_path / "runtime"
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

    provenance = read_result_provenance(con, run_id=_RUN_ID)
    assert len(provenance) == 1
    assert provenance[0]["synthetic_only"] is True
    neighborhoods = read_baseline_neighborhoods(con, run_id=_RUN_ID)
    assert neighborhoods
    assert all(row["query_song_id"] != row["candidate_song_id"] for row in neighborhoods)
    con.close()
