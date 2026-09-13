from types import SimpleNamespace

import duckdb
import pytest

from scripts.embedding_research.common.head_analysis import GeometryHeadOutput
from scripts.embedding_research.db import (
    IdentityRefusal,
    ensure_schema,
    read_analysis_rows,
    read_head_evidence,
    write_analysis_rows,
    write_head_evidence,
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


def test_head_evidence_reads_only_complete_exact_identity_axes():
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    output = GeometryHeadOutput(
        **{key: value for key, value in identity().__dict__.items() if key != "threshold_id"},
        threshold_id="t",
        head="head",
        segment_id=0,
        member_patch_indices=(0,),
        class1=0.5,
        searchable_weight=1.0,
        observed_medoid_source_index=0,
        observed_medoid_centrality=0.1,
        collapse_class_id="collapse",
        collapse_member_threshold_indices=(0,),
    )
    write_head_evidence(con, run_id="r", outputs=[output])
    assert read_head_evidence(con, run_id="r", identity=identity()) == (output.to_dict(),)
    for mutation in ("structural_identity", "scoring_semantics_version"):
        changed = identity(**{mutation: "other" if mutation == "structural_identity" else 2})
        with pytest.raises(IdentityRefusal):
            read_head_evidence(con, run_id="r", identity=changed)
    with pytest.raises(IdentityRefusal):
        read_head_evidence(con, run_id="r", identity=identity(threshold_id="missing"))
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
