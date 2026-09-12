"""Static and synthetic guards for geometry-bound head analysis."""

from pathlib import Path
from types import MappingProxyType

import pytest

from scripts.embedding_research.common.head_analysis import (
    GeometryHeadRefusalError,
    run_shared_geometry_head_analysis,
)

SOURCE = Path(__file__).parents[1].joinpath("common", "head_analysis.py").read_text()


def test_geometry_runner_is_cpu_and_stream_gather_free() -> None:
    start = SOURCE.index("def run_shared_geometry_head_analysis")
    end = SOURCE.find("\n\ndef ", start + 1)
    body = SOURCE[start:] if end < 0 else SOURCE[start:end]
    assert "head_store.batch_gather(" not in body
    assert "onnx" not in body.lower()
    assert "cuda" not in body.lower()
    assert "audio" not in body.lower()
    assert "resegment(" not in body.lower()


def test_geometry_runner_requires_aligned_persisted_head_payload() -> None:
    class Identity:
        song_id = "song"
        backbone = "effnet"
        geometry_id = "geometry"
        evidence = MappingProxyType({})

    class Analysis:
        observation_id = "observation"
        geometry_semantics_version = "gram-v1"
        profile_digest = "profile"
        evaluation_id = "evaluation"
        execution_id = "execution"
        results = ()

    with pytest.raises(GeometryHeadRefusalError, match="payload seam"):
        run_shared_geometry_head_analysis(Identity(), object(), analysis=Analysis(), run_id="run")


def test_geometry_runner_source_preserves_required_evidence_names() -> None:
    for name in (
        "geometry_id",
        "observation_id",
        "threshold_id",
        "structural_identity",
        "search_representation_id",
        "evaluation_id",
        "execution_id",
        "observed_medoid_source_index",
        "collapse_class_id",
    ):
        assert name in SOURCE
