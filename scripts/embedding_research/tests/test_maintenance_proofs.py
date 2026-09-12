"""Plan P supersession/resource refusal proofs for every geometry-derived seam.

Synthetic only: real corpus, audio, models, ONNX, and CUDA are never touched.  Each
test injects a superseding committed observation *around* a seam and proves the seam
fails closed with a typed refusal and never publishes clean derived evidence.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.cleanup import cleanup_current, reset_analysis
from scripts.embedding_research.common.geometry_analysis import (
    GeometryCorpusRequest,
    GeometrySongRequest,
    analyze_geometry_corpus,
)
from scripts.embedding_research.common.head_analysis import run_shared_geometry_head_analysis
from scripts.embedding_research.common.threshold_analysis import (
    analyze_all_thresholds,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db import ensure_schema, read_geometry, write_geometry
from scripts.embedding_research.db.geometry import (
    MAX_PATCH_COUNT,
    GeometryIdentity,
    IntegrityRefused,
    StaleRefused,
    enforce_geometry_resource_ceiling,
    preflight_geometry_binding,
    require_current_geometry,
    verify_geometry_current,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.streams.masks import MaskPayload
from scripts.embedding_research.streams.reindex import reconcile_current_manifests
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore
from scripts.embedding_research.verify import verify_current_artifacts

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

SONG = "s1"
BACKBONE = "effnet"
PATCH = 3
DIM = 2
AUDIO = "0" * 64


def _fresh_con():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    return con


@pytest.fixture
def profile() -> GeometryProfile:
    return GeometryProfile.current()


class _Bound:
    """Carry the primary DuckDB connection alongside one committed observation."""

    def __init__(self, con, committed) -> None:
        self.con = con
        self.identity = committed.identity
        self.stream = committed.stream
        self.mask = committed.mask
        self.stream_record = committed.stream_record
        self.provenance_identity = committed.provenance_identity


class _LateSupersedingStore:
    """Return a cached pre-supersession observation once, then the current one."""

    def __init__(self, inner, first_observation) -> None:
        self._inner = inner
        self._first = first_observation
        self._count = 0

    def load_committed_observation(self, song_id, backbone):
        self._count += 1
        if self._count == 1:
            return self._first
        return self._inner.load_committed_observation(song_id, backbone)

    def batch_gather(self, song_id, backbone, indices, *, forbid_duplicates):
        del song_id, backbone, forbid_duplicates
        values = tuple(indices)
        return np.asarray(self._first.stream[list(values)], dtype=np.float32)


def _publish_group(root: Path, con, *, run_id: str, emb: np.ndarray, audio: str = AUDIO):
    store = StreamStore(con, output_root=root)
    record = store.publish(SONG, BACKBONE, emb, run_id=run_id)
    store.publish_observation_group(
        record,
        MaskPayload(
            song_id=SONG,
            backbone=BACKBONE,
            patch_count=PATCH,
            mask=np.ones(PATCH, dtype=np.uint8),
            run_id=run_id,
            params_id=f"mask-params-{run_id}",
            audio_content_sha256=audio,
        ),
    )
    return store


def _seed(root: Path, con, *, with_head: bool = False):
    """Publish one committed group (+ optional aligned head payload) and its geometry."""
    root.mkdir(parents=True, exist_ok=True)
    store = _publish_group(root, con, run_id="run-1", emb=np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32))
    reconcile_current_manifests(root, con)
    if with_head:
        HeadStreamStore(con, output_root=root).publish(
            SONG,
            BACKBONE,
            {"head_logit": np.arange(PATCH * 2, dtype=np.float32).reshape(PATCH, 2)},
            run_id="run-1",
            patch_count=PATCH,
            alignment_version="1",
            expected_head_ids={"head_logit"},
            stream_ref=store.lookup(SONG, BACKBONE).artifact_ref,
        )
        reconcile_current_manifests(root, con)
    first = store.load_committed_observation(SONG, BACKBONE)
    geometry = write_geometry(_Bound(con, first), GeometryProfile.current(), "run-1")
    return store, first, geometry


def _supersede(root: Path, con):
    """Publish a newer committed group for the same song/backbone (new commit)."""
    store = _publish_group(root, con, run_id="run-2", emb=np.asarray([[2, 0], [0, 2], [2, 2]], dtype=np.float32))
    return store, store.load_committed_observation(SONG, BACKBONE)


def _request(record) -> GeometryCorpusRequest:
    identity = GeometryIdentity(
        record.identity.song_id,
        record.identity.backbone,
        record.identity.observation_commit_sha256,
        record.identity.geometry_semantics_version,
        record.identity.numerical_profile_digest,
    )
    return GeometryCorpusRequest(
        items=(
            GeometrySongRequest(
                SONG,
                BACKBONE,
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


def _scorer():
    def score(query, weights, candidate):
        del query, weights, candidate
        return SimpleNamespace(finite=True, score=0.5)

    return score


# ── geometry open / write ─────────────────────────────────────────────────────


def test_geometry_open_refuses_superseded_observation(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    store, _first, _record = _seed(root, con)
    _supersede(root, con)

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        require_current_geometry(SONG, BACKBONE, con, store=store, profile=profile)
    con.close()


def test_geometry_preflight_after_supersession_refuses(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    store, _first, record = _seed(root, con)
    _supersede(root, con)

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        preflight_geometry_binding(record, profile, store=store)
    con.close()


def test_geometry_write_refuses_resource_ceiling_before_any_write(tmp_path):
    con = _fresh_con()
    root = tmp_path / "root"
    _store, first, _record = _seed(root, con)
    bound = _Bound(con, first)
    bound.stream_record = replace(bound.stream_record, patch_count=MAX_PATCH_COUNT + 1)

    before = {p.name for p in (root / "streams").iterdir()} if (root / "streams").is_dir() else set()
    with pytest.raises(IntegrityRefused, match="resource refusal"):
        write_geometry(bound, GeometryProfile.current(), "run-resource")
    assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 1
    after = {p.name for p in (root / "streams").iterdir()} if (root / "streams").is_dir() else set()
    assert after == before
    con.close()


def test_resource_ceiling_refuses_invalid_and_oversized_patch_counts():
    for value in (0, -1, True, MAX_PATCH_COUNT + 1):
        with pytest.raises(IntegrityRefused, match="resource refusal"):
            enforce_geometry_resource_ceiling(value)
    enforce_geometry_resource_ceiling(MAX_PATCH_COUNT)


# ── persistence durability: reopen / checkpoint / crash ───────────────────────


def test_geometry_survives_reopen_and_checkpoint(tmp_path):
    db_path = tmp_path / "db.duckdb"
    root = tmp_path / "root"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _store, _first, record = _seed(root, con)
    con.execute("CHECKPOINT")
    con.close()

    reopened = duckdb.connect(str(db_path))
    loaded = read_geometry(record.identity, reopened)
    assert loaded.geometry_id == record.geometry_id
    assert loaded.gram_blob == record.gram_blob
    assert np.array_equal(loaded.matrix, record.matrix)
    reopened.close()


def test_geometry_crash_before_commit_leaves_no_row(tmp_path, profile):
    db_path = tmp_path / "db.duckdb"
    root = tmp_path / "root"
    root.mkdir()
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    store = _publish_group(root, con, run_id="run-1", emb=np.asarray([[1, 0], [0, 1], [1, 1]], dtype=np.float32))
    observation = _Bound(con, store.load_committed_observation(SONG, BACKBONE))

    class _CrashOnCommit:
        def execute(self, sql, params=None):
            if isinstance(sql, str) and sql.strip().upper() == "COMMIT":
                raise RuntimeError("injected crash before commit")
            return con.execute(sql, params) if params is not None else con.execute(sql)

    observation.con = _CrashOnCommit()
    with pytest.raises(RuntimeError, match="injected crash"):
        write_geometry(observation, profile, "run-crash")
    assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 0
    con.close()

    reopened = duckdb.connect(str(db_path))
    assert reopened.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 0
    assert verify_geometry_current(reopened, observation, profile=profile) is None
    reopened.close()


# ── verify / reindex / cleanup seams ──────────────────────────────────────────


def test_verify_refuses_superseded_geometry(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    _seed(root, con)
    _supersede(root, con)

    report = verify_current_artifacts(root, con=con, profile=profile)
    assert report.refusals
    assert any("STALE_REFUSED" in refusal for refusal in report.refusals)
    con.close()


def test_verify_refuses_absent_geometry_for_committed_observation(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    _publish_group(root, con, run_id="run-1", emb=np.ones((PATCH, DIM), dtype=np.float32))

    report = verify_current_artifacts(root, con=con, profile=profile)
    assert report.refusals
    assert any("no committed geometry" in refusal for refusal in report.refusals)
    con.close()


def test_reindex_refuses_superseded_geometry(tmp_path):
    con = _fresh_con()
    root = tmp_path / "root"
    _seed(root, con)
    _supersede(root, con)

    report = reconcile_current_manifests(root, con)
    assert report.issues
    assert report.ready == 0
    assert not report.clean
    con.close()


def test_cleanup_refuses_superseded_geometry_and_removes_nothing(tmp_path):
    con = _fresh_con()
    root = tmp_path / "root"
    _seed(root, con)
    _supersede(root, con)
    stray = root / "streams" / f"s1.effnet.{'a' * 64}.npy"
    stray.write_bytes(b"orphan-payload")

    report = cleanup_current(root, con, scope="stray", dry_run=False)
    assert report.refused
    assert not report.changed
    assert stray.is_file()
    con.close()


# ── analyze seam: before and after computation ────────────────────────────────


def test_analyze_refuses_supersession_after_computation(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    store, first, record = _seed(root, con)
    _supersede(root, con)
    late_store = _LateSupersedingStore(store, first)

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        analyze_geometry_corpus(_request(record), con=con, stream_store=late_store, profile=profile, scoring=_scorer())
    con.close()


# ── head-analysis seam: before and after computation ──────────────────────────


def test_head_analysis_refuses_supersession_before_computation(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    store, first, record = _seed(root, con, with_head=True)
    _supersede(root, con)
    superseded = store.load_committed_observation(SONG, BACKBONE)
    analysis = analyze_all_thresholds(record, first.mask, dense_primary_threshold_request())

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        run_shared_geometry_head_analysis(
            record,
            HeadStreamStore(con, output_root=root),
            analysis=analysis,
            run_id="run-1",
            current_observation=superseded,
            profile=profile,
        )
    con.close()


def test_head_analysis_refuses_supersession_after_computation(tmp_path, profile):
    con = _fresh_con()
    root = tmp_path / "root"
    _store, first, record = _seed(root, con)
    analysis = analyze_all_thresholds(record, first.mask, dense_primary_threshold_request())
    _supersede(root, con)
    superseding_store = StreamStore(con, output_root=root)
    head_store = _FakeHeadStore(np.arange(PATCH * 2, dtype=np.float32).reshape(PATCH, 2))

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        run_shared_geometry_head_analysis(
            record,
            head_store,
            analysis=analysis,
            run_id="run-1",
            current_observation=first,
            profile=profile,
            stream_store=superseding_store,
        )
    con.close()


# ── report seam ───────────────────────────────────────────────────────────────


class _HeadPayload:
    head_ids = "head_logit"
    dim_by_head = "head_logit=2"

    def __init__(self, matrix: np.ndarray) -> None:
        self.matrix = matrix


class _FakeHeadStore:
    def __init__(self, matrix: np.ndarray) -> None:
        self._matrix = matrix

    def load(self, song_id, backbone):
        del song_id, backbone
        return _HeadPayload(self._matrix)


def _insert_corpus_evidence(con, record, *, run_id: str) -> None:
    axes = [
        {
            "song_id": record.identity.song_id,
            "backbone": record.identity.backbone,
            "observation_id": record.identity.observation_commit_sha256,
            "geometry_semantics_version": record.identity.geometry_semantics_version,
            "numerical_profile_digest": record.identity.numerical_profile_digest,
            "geometry_id": record.geometry_id,
        }
    ]
    evidence = json.dumps({"role": "corpus", "geometry_axes": axes})
    con.execute(
        "INSERT INTO geometry_analysis_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            run_id,
            record.geometry_id,
            record.identity.observation_commit_sha256,
            record.identity.geometry_semantics_version,
            record.identity.numerical_profile_digest,
            "threshold:0",
            "structural",
            "representation",
            "evaluation-a",
            1,
            "execution-a",
            "metric-a",
            1.0,
            evidence,
            1,
        ),
    )


def test_report_refuses_superseded_geometry_before_publication(tmp_path, profile):
    from scripts.embedding_research.report import run as report_run

    con = _fresh_con()
    root = tmp_path / "root"
    store, _first, record = _seed(root, con)
    _insert_corpus_evidence(con, record, run_id="run-a")
    _supersede(root, con)
    out_dir = tmp_path / "out"

    with pytest.raises(StaleRefused, match="STALE_REFUSED"):
        report_run(con, out_dir, run_id="run-a", stream_store=store, profile=profile)
    assert not (out_dir / "report.json").exists()
    assert not (out_dir / "report.html").exists()
    con.close()


# ── analysis reset: geometry byte preservation + post-reset rerun ─────────────


def test_analysis_reset_preserves_geometry_and_allows_post_reset_rerun(tmp_path, profile):
    """Reset clears only analysis rows; the preserved geometry still drives analyze."""
    db_path = tmp_path / "db.duckdb"
    root = tmp_path / "root"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    _store, _first, record = _seed(root, con)
    con.execute("INSERT INTO analyze_metrics VALUES ('run-a','geometry:s1','geometry','l2',1,'metric',0.5)")
    before = con.execute(
        "SELECT geometry_id, geometry_blob_sha256, geometry_blob_byte_length, gram_blob "
        "FROM song_patch_geometry ORDER BY geometry_id"
    ).fetchall()
    con.close()

    reset_analysis(root, db_path)

    reopened = duckdb.connect(str(db_path))
    after = reopened.execute(
        "SELECT geometry_id, geometry_blob_sha256, geometry_blob_byte_length, gram_blob "
        "FROM song_patch_geometry ORDER BY geometry_id"
    ).fetchall()
    assert after == before
    assert reopened.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0

    # Post-reset rerun: the preserved geometry still drives the analyze owner.
    rerun_store = StreamStore(reopened, output_root=root)
    rerun = analyze_geometry_corpus(
        _request(record), con=reopened, stream_store=rerun_store, profile=profile, scoring=_scorer()
    )
    assert rerun.counters.geometry_load_count >= 1
    reopened.close()


# ── exclusive run lock contention ─────────────────────────────────────────────


def test_exclusive_run_lock_contention_refuses(tmp_path):
    from scripts.embedding_research import run as run_mod

    root = tmp_path / "root"
    root.mkdir()
    db_path = tmp_path / "db.duckdb"

    with run_mod._RunLock(root, db_path), pytest.raises(SystemExit) as excinfo, run_mod._RunLock(root, db_path):
        pass
    assert excinfo.value.code == 2
