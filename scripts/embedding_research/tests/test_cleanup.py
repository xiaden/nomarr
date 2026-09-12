"""Geometry-era cleanup/reset tests: disposable scopes and immutable geometry evidence.

Only the two current-format cleanup scopes (leftover staging ``.tmp`` files and
digest payloads with no sibling manifest) are exercised, plus the named
``GEOMETRY_RESET_UNAVAILABLE`` refusal and the analysis reset that must preserve
every ``song_patch_geometry`` byte.  Synthetic temp roots and in-memory DuckDB
only; no real corpus, audio, models, or filesystem Gram.
"""

from __future__ import annotations

import hashlib

import duckdb
import pytest

from scripts.embedding_research.cleanup import (
    GeometryResetUnavailableError,
    cleanup_current,
    reset_analysis,
    reset_geometry,
)
from scripts.embedding_research.db._schema import ensure_schema, schema_fingerprint


def _write(root, rel: str, content: bytes = b"x"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _digest_name(song: str, backbone: str, suffix: str) -> str:
    return f"{song}.{backbone}.{'a' * 64}{suffix}"


# ── disposable cleanup scopes ────────────────────────────────────────────────


def test_cleanup_staging_dry_run_reports_without_removing(tmp_path):
    leftover = _write(tmp_path, "streams/.staging/stream.tmp", b"tmp")

    report = cleanup_current(tmp_path, None, scope="staging")

    assert report.scope == "staging"
    assert report.dry_run is True
    assert report.removed == [str(leftover)]
    assert leftover.exists()


def test_cleanup_staging_removes_leftover_tmp_when_not_dry_run(tmp_path):
    leftover = _write(tmp_path, "heads/.staging/head.tmp", b"tmp")

    report = cleanup_current(tmp_path, None, scope="staging", dry_run=False)

    assert report.changed
    assert not leftover.exists()


def test_cleanup_stray_removes_orphan_digest_payload_only(tmp_path):
    orphan = _write(tmp_path, f"streams/{_digest_name('s1', 'effnet', '.npy')}", b"data")
    kept = _write(tmp_path, f"streams/{_digest_name('s2', 'effnet', '.npy')}", b"data")
    _write(tmp_path, f"streams/{_digest_name('s2', 'effnet', '.json')}", b"{}")

    report = cleanup_current(tmp_path, None, scope="stray", dry_run=False)

    assert report.removed == [str(orphan)]
    assert not orphan.exists()
    assert kept.exists()


def test_cleanup_stray_ignores_non_digest_names(tmp_path):
    bare = _write(tmp_path, "streams/song.npy", b"bare")

    report = cleanup_current(tmp_path, None, scope="stray", dry_run=False)

    assert not report.changed
    assert bare.exists()


def test_cleanup_unknown_scope_is_refused(tmp_path):
    report = cleanup_current(tmp_path, None, scope="unknown", dry_run=False)  # type: ignore[arg-type]

    assert report.refused
    assert not report.changed


# ── reset: analysis preserved upstream, geometry immutable ───────────────────


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


def _insert_geometry(con, row: dict[str, object]) -> None:
    columns = tuple(row)
    con.execute(
        f"INSERT INTO song_patch_geometry ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(row.values()),
    )


def test_reset_analysis_preserves_geometry_bytes(tmp_path):
    db_path = tmp_path / "db.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    row = _geometry_row()
    columns = tuple(row)
    con.execute(
        f"INSERT INTO song_patch_geometry ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(row.values()),
    )
    con.execute("INSERT INTO analyze_metrics VALUES ('run-1','geometry:s1','geometry','l2',1,'metric',0.5)")
    con.close()
    digest_before = hashlib.sha256(row["gram_blob"]).hexdigest()  # type: ignore[arg-type]

    report = reset_analysis(tmp_path, db_path)

    assert report.removed
    check = duckdb.connect(str(db_path), read_only=True)
    preserved = check.execute("SELECT gram_blob FROM song_patch_geometry").fetchone()[0]
    assert preserved == row["gram_blob"]
    assert hashlib.sha256(preserved).hexdigest() == digest_before
    assert check.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0
    check.close()


def test_reset_analysis_preserves_every_geometry_byte_and_schema(tmp_path):
    """Every geometry row survives byte-for-byte and the schema fingerprint is unchanged."""
    db_path = tmp_path / "db.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    before_rows: list[tuple[object, ...]] = []
    for index, blob in enumerate((b"geometry-bytes\x00\xff", b"second\x00blob\xfe")):
        row = {
            **_geometry_row(),
            "geometry_id": f"g{index}",
            "song_id": f"s{index}",
            "gram_blob": blob,
            "geometry_blob_byte_length": len(blob),
            "geometry_blob_sha256": hashlib.sha256(blob).hexdigest(),
        }
        _insert_geometry(con, row)
        before_rows.append((row["geometry_id"], row["geometry_blob_sha256"], row["geometry_blob_byte_length"], blob))
    con.execute("INSERT INTO analyze_metrics VALUES ('run-1','geometry:s1','geometry','l2',1,'metric',0.5)")
    fingerprint_before = schema_fingerprint(con)
    con.close()

    reset_analysis(tmp_path, db_path)

    check = duckdb.connect(str(db_path), read_only=True)
    after_rows = check.execute(
        "SELECT geometry_id, geometry_blob_sha256, geometry_blob_byte_length, gram_blob "
        "FROM song_patch_geometry ORDER BY geometry_id"
    ).fetchall()
    assert after_rows == before_rows
    assert schema_fingerprint(check) == fingerprint_before
    assert check.execute("SELECT COUNT(*) FROM analyze_metrics").fetchone()[0] == 0
    check.close()


def test_reset_analysis_preserves_corpus_state(tmp_path):
    """Analysis reset never clears the upstream embed-phase corpus_state singleton."""
    from scripts.embedding_research.db import update_corpus_state

    db_path = tmp_path / "db.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    update_corpus_state(con, state_version=1, registered_song_count=2, reconciled_at=1)
    con.close()

    reset_analysis(tmp_path, db_path)

    check = duckdb.connect(str(db_path), read_only=True)
    assert check.execute("SELECT COUNT(*) FROM corpus_state").fetchone()[0] == 1
    assert check.execute("SELECT registered_song_count FROM corpus_state").fetchone()[0] == 2
    check.close()


def test_reset_cli_refuses_geometry_and_unknown_scopes():
    """The CLI refuses geometry reset (typed) and every non-analysis scope (exit 2)."""
    from types import SimpleNamespace

    from scripts.embedding_research import run as run_mod

    with pytest.raises(SystemExit) as geometry_exit:
        run_mod._cmd_reset(SimpleNamespace(scope="geometry", dry_run=True))
    assert "GEOMETRY_RESET_UNAVAILABLE" in str(geometry_exit.value)

    for scope in ("unknown", "staging", "stray", "views", "dead"):
        with pytest.raises(SystemExit) as unknown_exit:
            run_mod._cmd_reset(SimpleNamespace(scope=scope, dry_run=True))
        assert unknown_exit.value.code == 2


def test_reset_geometry_is_unavailable():
    with pytest.raises(GeometryResetUnavailableError, match="GEOMETRY_RESET_UNAVAILABLE"):
        reset_geometry()
