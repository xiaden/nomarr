"""R12 — analysis reset preserves geometry bytes; geometry reset is unavailable."""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.cleanup import GeometryResetUnavailableError, reset_analysis, reset_geometry
from scripts.embedding_research.db._schema import ensure_schema, schema_fingerprint
from scripts.embedding_research.db.geometry import read_geometry, write_geometry
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tests._gram_evidence import SyntheticObservation, emit_evidence, sha256_bytes


def test_analysis_reset_preserves_geometry_bytes(tmp_path) -> None:
    db_path = tmp_path / "research.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    fingerprint = schema_fingerprint(con)
    record = write_geometry(SyntheticObservation(con), GeometryProfile.current(), "run-reset")
    row = con.execute(
        "SELECT gram_blob, geometry_blob_byte_length, geometry_blob_sha256, observation_commit_sha256 "
        "FROM song_patch_geometry WHERE geometry_id = ?",
        [record.geometry_id],
    ).fetchone()
    identity = record.identity
    con.close()

    report = reset_analysis(tmp_path, db_path)
    assert report.removed, "analysis reset must report removed disposable state"

    reopened = duckdb.connect(str(db_path), read_only=True)
    try:
        assert schema_fingerprint(reopened) == fingerprint
        assert reopened.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 1
        reread = read_geometry(identity, reopened)
        assert reread.gram_blob == row[0]
        assert len(reread.gram_blob) == row[1]
        assert sha256_bytes(reread.gram_blob) == row[2]
        assert reread.identity.observation_commit_sha256 == row[3]
    finally:
        reopened.close()

    emit_evidence(
        "r12-analysis-reset-preserves-geometry.json",
        {
            "schema_fingerprint": fingerprint,
            "geometry_row_count": 1,
            "geometry_blob_sha256": row[2],
            "geometry_blob_byte_length": row[1],
        },
    )


def test_geometry_scope_refuses() -> None:
    with pytest.raises(GeometryResetUnavailableError) as excinfo:
        reset_geometry()
    assert excinfo.value.code == "GEOMETRY_RESET_UNAVAILABLE"
    with pytest.raises(GeometryResetUnavailableError):
        reset_geometry("analysis")
    emit_evidence(
        "r12-geometry-reset-refusal.json",
        {"code": "GEOMETRY_RESET_UNAVAILABLE", "geometry_reset_available": False},
    )
