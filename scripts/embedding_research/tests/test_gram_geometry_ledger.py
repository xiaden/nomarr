"""R1 — exact ``song_patch_geometry`` ledger schema, byte round trip, and no filesystem Gram.

Deterministic synthetic evidence for the pinned single-writer DuckDB geometry ledger:
one complete little-endian float32 C-order Gram BLOB per exact observation identity,
addressed by the full five-field identity, with no filesystem Gram sidecar.
"""

from __future__ import annotations

import ast
from pathlib import Path

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import GEOMETRY_COLUMNS, ensure_schema, schema_fingerprint
from scripts.embedding_research.db.geometry import (
    GeometryRefusal,
    IntegrityRefused,
    read_geometry,
    read_geometry_matrix,
    write_geometry,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tests._gram_evidence import (
    EVIDENCE_ROOT,
    SyntheticObservation,
    duplicate_geometry_row,
    emit_evidence,
    sha256_bytes,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_song_patch_geometry_schema_fingerprint_and_one_row_round_trip() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        columns = tuple(
            str(row[0])
            for row in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'song_patch_geometry' ORDER BY ordinal_position"
            ).fetchall()
        )
        assert columns == GEOMETRY_COLUMNS
        assert (
            con.execute("SELECT count(*) FROM duckdb_indexes() WHERE table_name = 'song_patch_geometry'").fetchone()[0]
            == 0
        )
        fingerprint = schema_fingerprint(con)
        assert fingerprint == schema_fingerprint(con)
        assert len(fingerprint) == 64

        profile = GeometryProfile.current()
        record = write_geometry(SyntheticObservation(con), profile, "run-ledger")
        blob = record.gram_blob
        side = record.matrix.shape[0]
        assert len(blob) == 4 * side * side
        reread = read_geometry(record.identity, con)
        assert reread.evidence["geometry_blob_byte_length"] == len(blob)
        assert reread.evidence["geometry_blob_sha256"] == sha256_bytes(blob)

        decoded = np.frombuffer(blob, dtype="<f4")
        assert decoded.dtype == np.dtype("<f4")
        matrix = decoded.reshape((side, side), order="C")
        assert np.array_equal(matrix, np.asarray(record.matrix))
        assert not record.matrix.flags.writeable

        assert reread.gram_blob == blob
        assert np.array_equal(read_geometry_matrix(record.identity, con), matrix)

        with pytest.raises(GeometryRefusal, match="already exists"):
            write_geometry(SyntheticObservation(con), profile, "run-duplicate")

        duplicate_geometry_row(con, "duplicate-geometry-id")
        with pytest.raises(GeometryRefusal, match="expected one row"):
            read_geometry(record.identity, con)

        emit_evidence(
            "r1-schema-fingerprint.json",
            {
                "schema_fingerprint": fingerprint,
                "column_count": len(GEOMETRY_COLUMNS),
                "gram_byte_length": len(blob),
                "gram_sha256": sha256_bytes(blob),
                "patch_count": side,
                "duplicate_write_refused": True,
                "ambiguous_row_refused": True,
            },
        )
    finally:
        con.close()


def test_no_filesystem_gram_artifact() -> None:
    self_path = Path(__file__).resolve()
    scanned: list[str] = []
    matches: list[dict[str, str]] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if path.resolve() == self_path:
            continue
        scanned.append(path.relative_to(_PACKAGE_ROOT).as_posix())
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):  # pragma: no cover - unreadable source
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in {"save", "savez", "savez_compressed", "open"}:
                continue
            for argument in node.args:
                if (
                    isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    and "gram" in argument.value.lower()
                ):
                    matches.append({"path": path.name, "call": name, "literal": argument.value})  # noqa: PERF401

    assert matches == [], f"filesystem Gram write reachable: {matches}"
    artifacts = [
        str(candidate)
        for pattern in ("*gram*.npy", "*gram*.npz", "*gram*.bin", "*gram*.blob", "*gram*.dat")
        for candidate in _PACKAGE_ROOT.rglob(pattern)
    ]
    assert artifacts == [], f"on-disk Gram artifacts exist: {artifacts}"
    emit_evidence(
        "r1-no-filesystem-gram.json",
        {
            "scanned_files": len(scanned),
            "filesystem_gram_matches": matches,
            "filesystem_gram_artifacts": artifacts,
        },
    )
    assert EVIDENCE_ROOT.is_dir()


def test_geometry_lock_token_rollback_and_resource_gate() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    profile = GeometryProfile.current()
    observation = SyntheticObservation(con)
    try:
        with pytest.raises(IntegrityRefused, match="invalid exclusive run lock token"):
            write_geometry(observation, profile, "run-storage", lock=object())
        assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 0

        class _HeldLock:
            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

        write_geometry(observation, profile, "run-storage", lock=_HeldLock())
        assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 1

        class FailingConnection:
            def execute(self, sql, params=None):
                if isinstance(sql, str) and sql.startswith("INSERT INTO song_patch_geometry"):
                    raise RuntimeError("injected insert failure")
                return con.execute(sql, params) if params is not None else con.execute(sql)

        failing = SyntheticObservation(con, song_id="song-2", commit="commit-2")
        failing.con = FailingConnection()
        with pytest.raises(RuntimeError, match="injected"):
            write_geometry(failing, profile, "run-storage")
        assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 1
    finally:
        con.close()
    emit_evidence(
        "r1-storage-lifecycle.json",
        {"lock_refusal": True, "held_lock_accepted": True, "rollback_left_no_partial_row": True},
    )


def test_geometry_reopen_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "geometry.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    profile = GeometryProfile.current()
    record = write_geometry(SyntheticObservation(con), profile, "run-reopen")
    con.close()

    reopened = duckdb.connect(str(db_path))
    ensure_schema(reopened)
    try:
        reread = read_geometry(record.identity, reopened)
        assert reread.geometry_id == record.geometry_id
        assert bytes(reread.gram_blob) == bytes(record.gram_blob)
        np.testing.assert_array_equal(reread.matrix, record.matrix)
    finally:
        reopened.close()
