"""Head-evidence identity round trip and refusal contracts.

The retired per-axis analysis-row persistence round trip was hard-cut with the nested
result model; only the head-evidence identity contract remains here.
"""

from types import SimpleNamespace

import duckdb
import pytest

from scripts.embedding_research.common.head_analysis import GeometryHeadOutput
from scripts.embedding_research.db import (
    IdentityRefusal,
    ensure_schema,
    read_head_evidence,
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
