"""R2 — complete observation binding with fail-closed refusal for every tamper class.

Covers exact identity/profile refusal, tampered evidence, missing mask, duplicate rows,
non-finite / wrong-length / malformed BLOB, wrong stream dtype, and resource ceilings.
No alternate/repair branch exists: every failure is the typed refusal.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.geometry import (
    MAX_PATCH_COUNT,
    GeometryRefusal,
    IntegrityRefused,
    enforce_geometry_resource_ceiling,
    read_geometry,
    verify_geometry_binding,
    verify_geometry_current,
    write_geometry,
)
from scripts.embedding_research.db.geometry_profile import GeometryProfile
from scripts.embedding_research.tests._gram_evidence import (
    SyntheticObservation,
    duplicate_geometry_row,
    emit_evidence,
    update_geometry_blob,
)


def _seed(con, **kwargs):
    return write_geometry(SyntheticObservation(con, **kwargs), GeometryProfile.current(), "run-binding")


def test_binding_tamper_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        con.execute(
            "UPDATE song_patch_geometry SET stream_ref = 'tampered' WHERE geometry_id = ?", [record.geometry_id]
        )
        tampered = read_geometry(record.identity, con)
        with pytest.raises(IntegrityRefused, match="evidence mismatch"):
            verify_geometry_binding(tampered, SyntheticObservation(con), GeometryProfile.current())
        emit_evidence(
            "r2-binding-tamper-refusal.json",
            {"refusals": [{"code": "INTEGRITY_REFUSED", "surface": "evidence tuple", "refused": True}]},
        )
    finally:
        con.close()


def test_missing_mask_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        with pytest.raises(IntegrityRefused, match="missing"):
            _seed(con, mask_digest=None)
        assert con.execute("SELECT count(*) FROM song_patch_geometry").fetchone()[0] == 0
    finally:
        con.close()


def test_duplicate_row_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        duplicate_geometry_row(con, "duplicate-geometry-id")
        with pytest.raises(IntegrityRefused, match="duplicate geometry rows"):
            verify_geometry_current(con, SyntheticObservation(con), profile=GeometryProfile.current())
        assert record.geometry_id != "duplicate-geometry-id"
    finally:
        con.close()


def test_nonfinite_blob_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        side = record.matrix.shape[0]
        blob = np.full(side * side, np.nan, dtype="<f4").tobytes()
        update_geometry_blob(con, record.geometry_id, blob, fix_digest=True, fix_length=True)
        with pytest.raises(GeometryRefusal, match="non-finite"):
            read_geometry(record.identity, con)
    finally:
        con.close()


def test_wrong_length_wrong_dtype_and_malformed_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        # digest/shape mismatch: blob is not P*P float32 cells.
        update_geometry_blob(con, record.geometry_id, b"\x00" * 4, fix_digest=True, fix_length=True)
        with pytest.raises(GeometryRefusal, match="integrity validation failed"):
            read_geometry(record.identity, con)
    finally:
        con.close()

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        # tampered bytes without a matching digest.
        update_geometry_blob(
            con, record.geometry_id, b"\x01" * len(record.gram_blob), fix_digest=False, fix_length=True
        )
        with pytest.raises(GeometryRefusal, match="integrity validation failed"):
            read_geometry(record.identity, con)
    finally:
        con.close()

    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        wrong_dtype = SyntheticObservation(con)
        wrong_dtype.stream = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float64)
        with pytest.raises(GeometryRefusal):
            write_geometry(wrong_dtype, GeometryProfile.current(), "run-wrong-dtype")
        assert enforce_geometry_resource_ceiling(4) is None
        for bad in (0, -1, True, "4"):
            with pytest.raises(IntegrityRefused):
                enforce_geometry_resource_ceiling(bad)
        with pytest.raises(IntegrityRefused):
            enforce_geometry_resource_ceiling(MAX_PATCH_COUNT + 1)
    finally:
        con.close()


def test_profile_mismatch_refusal() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        record = _seed(con)
        other = GeometryProfile.from_manifest({"geometry_semantics_version": "other-semantics"})
        with pytest.raises(IntegrityRefused, match="binding mismatch"):
            verify_geometry_binding(record, SyntheticObservation(con), other)
        with pytest.raises(IntegrityRefused, match="malformed geometry profile"):
            write_geometry(SyntheticObservation(con), object(), "run-bad-profile")  # type: ignore[arg-type]
    finally:
        con.close()
