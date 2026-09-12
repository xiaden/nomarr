"""Focused maintenance gates for the current geometry/observation contract."""

from __future__ import annotations

import hashlib
import io
import json

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.cleanup import (
    GeometryResetUnavailableError,
    cleanup_current,
    reset_analysis,
    reset_geometry,
)
from scripts.embedding_research.db._schema import StaleSchemaError, ensure_schema
from scripts.embedding_research.streams.reindex import reconcile_current_manifests
from scripts.embedding_research.verify import verify_current_artifacts


def _geometry_row() -> dict[str, object]:
    blob = b"geometry-bytes\x00\xff"
    return {
        "geometry_id": "g1",
        "song_id": "s1",
        "backbone": "effnet",
        "observation_group_sha256": "commit",
        "stream_ref": "streams/s1.effnet.stream.npy",
        "stream_fingerprint_sha256": "stream",
        "stream_payload_sha256": "stream-payload",
        "mask_ref": "audio_masks/s1.effnet.mask.npy",
        "mask_payload_sha256": "mask-payload",
        "patch_count": 2,
        "embedding_dim": 3,
        "stream_dtype": "float32",
        "stream_format_version": "1",
        "embed_semantics_version": 1,
        "preprocess_fn": "identity",
        "preprocess_version": "1",
        "backbone_model_hash": "model",
        "audio_params": "{}",
        "provenance_source": "synthetic",
        "provenance_assumption": "synthetic",
        "alignment_token": "align",
        "audio_content_sha256": "audio",
        "mask_semantics_version": "1",
        "group_format_version": "1",
        "provenance_identity": "identity",
        "geometry_semantics_version": "1",
        "numerical_profile_digest": "profile",
        "geometry_blob_byte_length": len(blob),
        "geometry_blob_sha256": hashlib.sha256(blob).hexdigest(),
        "gram_blob": blob,
        "status": "committed",
        "writer_run_id": "run-1",
        "created_at_ms": 1,
        "updated_at_ms": 1,
    }


def _insert_geometry(con) -> bytes:
    row = _geometry_row()
    columns = tuple(row)
    con.execute(
        f"INSERT INTO song_patch_geometry ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(row.values()),
    )
    return row["gram_blob"]  # type: ignore[return-value]


def _npy_bytes(array: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, array)
    return stream.getvalue()


def _payload(root, subdir: str, array: np.ndarray, *, patch_count: int | None = None) -> None:
    data = _npy_bytes(array)
    digest = hashlib.sha256(data).hexdigest()
    directory = root / subdir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"s1.effnet.{digest}.npy"
    path.write_bytes(data)
    manifest = {"kind": subdir, "payload_sha256": digest}
    if patch_count is not None:
        manifest["patch_count"] = patch_count
    path.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")


def test_analysis_reset_preserves_geometry_bytes_and_committed_upstream_rows(tmp_path):
    db_path = tmp_path / "db.duckdb"
    commit_dir = tmp_path / "observation_commits"
    commit_dir.mkdir()
    marker = commit_dir / "s1.effnet.json"
    marker.write_text('{"song_id": "s1", "backbone": "effnet"}', encoding="utf-8")

    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    blob = _insert_geometry(con)
    con.execute("INSERT INTO songs VALUES ('s1', '/tmp/s1.wav', NULL, NULL, NULL, NULL)")
    stream_columns = [row[0] for row in con.execute("DESCRIBE stream_registry").fetchall()]
    con.execute(
        f"INSERT INTO stream_registry ({', '.join(stream_columns)}) VALUES ({', '.join('?' for _ in stream_columns)})",
        (
            "s1",
            "effnet",
            "streams/s1",
            2,
            3,
            "float32",
            "1",
            "stream",
            None,
            None,
            None,
            None,
            1,
            "synthetic",
            None,
            "ready",
            "run-1",
            1,
            1,
        ),
    )
    head_columns = [row[0] for row in con.execute("DESCRIBE head_stream_registry").fetchall()]
    con.execute(
        f"INSERT INTO head_stream_registry ({', '.join(head_columns)}) VALUES ({', '.join('?' for _ in head_columns)})",
        (
            "s1",
            "effnet",
            "heads/s1",
            2,
            '["h"]',
            '{"h": 1}',
            "1",
            "heads",
            None,
            None,
            None,
            "1",
            "ready",
            "run-1",
            1,
            1,
        ),
    )
    con.execute("INSERT INTO analyze_metrics VALUES ('run-1','geometry:s1','geometry','l2',1,'metric',0.5)")
    con.close()
    digest_before = hashlib.sha256(blob).hexdigest()

    report = reset_analysis(tmp_path, db_path)
    assert report.removed

    check = duckdb.connect(str(db_path), read_only=True)
    assert check.execute("SELECT COUNT(*) FROM song_patch_geometry").fetchone()[0] == 1
    preserved = check.execute("SELECT gram_blob FROM song_patch_geometry").fetchone()[0]
    assert preserved == blob
    assert hashlib.sha256(preserved).hexdigest() == digest_before
    assert check.execute("SELECT COUNT(*) FROM stream_registry").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM head_stream_registry").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1
    assert check.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0
    check.close()
    assert marker.is_file()


def test_geometry_reset_is_explicitly_unavailable():
    with pytest.raises(GeometryResetUnavailableError, match="GEOMETRY_RESET_UNAVAILABLE"):
        reset_geometry()


def test_pre_cut_and_mixed_analyze_schemas_refuse():
    for ddl in (
        "CREATE TABLE analyze_metrics (strategy_key TEXT)",
        "CREATE TABLE analyze_metrics (run_id TEXT, strategy_key TEXT)",
    ):
        con = duckdb.connect(":memory:")
        con.execute(ddl)
        with pytest.raises(StaleSchemaError):
            ensure_schema(con)
        con.close()


def test_verify_reindex_cleanup_refuse_bad_current_evidence(tmp_path):
    _payload(tmp_path, "streams", np.ones((2, 3), dtype=np.float32))
    _payload(tmp_path, "audio_masks", np.ones(3, dtype=np.float32), patch_count=3)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_text("not-json", encoding="utf-8")
    verification = verify_current_artifacts(tmp_path, strict=True)
    assert verification.refusals
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    report = reconcile_current_manifests(tmp_path, con)
    assert report.issues
    cleanup = cleanup_current(tmp_path, con, scope="stray", dry_run=False)
    assert not cleanup.changed
    con.close()


def test_maintenance_rejects_non_uint8_and_wrong_length_masks(tmp_path):
    for array, patch_count in ((np.ones(3, dtype=np.float32), 3), (np.ones(2, dtype=np.uint8), 3)):
        root = tmp_path / str(array.dtype) / str(array.size)
        _payload(root, "audio_masks", array, patch_count=patch_count)
        report = verify_current_artifacts(root, strict=True)
        assert report.refusals


def test_maintenance_creates_no_filesystem_derived_artifacts(tmp_path):
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    report = cleanup_current(tmp_path, con, scope="stray", dry_run=False)
    assert not report.changed
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert after == before
    con.close()
