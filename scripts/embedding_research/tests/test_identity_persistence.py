from types import SimpleNamespace

import duckdb
import pytest

from scripts.embedding_research.db import (
    IdentityRefusal,
    ensure_schema,
    read_analysis_rows,
    write_analysis_rows,
)


def identity(**overrides):
    values = {
        "geometry_id": "g",
        "observation_group_sha256": "o",
        "geometry_semantics_version": "gram-v1",
        "numerical_profile_digest": "p",
        "threshold_id": "t",
        "structural_identity": "struct",
        "evaluation_id": "e",
        "scoring_semantics_version": 1,
        "search_representation_id": "s",
        "execution_id": "x",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_analysis_roundtrip_reopen_and_exact_identity():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    write_analysis_rows(con, run_id="r", identity=identity(), metrics={"m": 1.25}, evidence={"songs": ["a"]})
    assert read_analysis_rows(con, run_id="r", identity=identity())[0]["value"] == pytest.approx(1.25)
    with pytest.raises(IdentityRefusal):
        read_analysis_rows(con, run_id="other", identity=identity())
    con.close()


def test_refuses_incomplete_nonfinite_duplicate_and_stale_identity():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    with pytest.raises(IdentityRefusal):
        write_analysis_rows(con, run_id="r", identity=identity(observation_group_sha256=""), metrics={"m": 1})
    with pytest.raises(IdentityRefusal):
        write_analysis_rows(con, run_id="r", identity=identity(), metrics={"m": float("nan")})
    write_analysis_rows(con, run_id="r", identity=identity(), metrics={"m": 1})
    with pytest.raises(IdentityRefusal):
        write_analysis_rows(con, run_id="r", identity=identity(), metrics={"m": 2})
    with pytest.raises(IdentityRefusal):
        read_analysis_rows(con, run_id="r", identity=identity(geometry_id="superseded"))
    con.close()
