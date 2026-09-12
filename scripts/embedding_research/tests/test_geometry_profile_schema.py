"""Synthetic evidence for the pinned geometry profile and schema."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from scripts.embedding_research.db._schema import GEOMETRY_COLUMNS, StaleSchemaError, ensure_schema, schema_fingerprint
from scripts.embedding_research.db.geometry_profile import GeometryProfile, profile_digest

EVIDENCE = Path(__file__).with_name("geometry_profile_schema_evidence.json")


def test_profile_round_trip_and_digest() -> None:
    profile = GeometryProfile.from_manifest({"b": "2", "a": "1"})
    assert profile.digest == profile_digest({"a": "1", "b": "2"})
    assert GeometryProfile.from_manifest(profile.to_manifest()) == profile


def test_schema_fingerprint_and_geometry_shape() -> None:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    assert schema_fingerprint(con) == schema_fingerprint(con)
    columns = tuple(row[0] for row in con.execute("DESCRIBE song_patch_geometry").fetchall())
    assert columns == GEOMETRY_COLUMNS
    indexes = con.execute("SELECT index_name FROM duckdb_indexes() WHERE table_name='song_patch_geometry'").fetchall()
    assert indexes == []
    con.close()


def test_malformed_geometry_schema_refuses() -> None:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE song_patch_geometry (geometry_id TEXT)")
    with pytest.raises(StaleSchemaError):
        schema_fingerprint(con)
    con.close()


def test_machine_readable_evidence() -> None:
    profile = GeometryProfile.from_manifest({"a": "1", "b": "2"})
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    evidence = {"profile_digest": profile.digest, "schema_fingerprint": schema_fingerprint(con), "synthetic_only": True}
    EVIDENCE.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
    assert json.loads(EVIDENCE.read_text(encoding="utf-8")) == evidence
    con.close()
