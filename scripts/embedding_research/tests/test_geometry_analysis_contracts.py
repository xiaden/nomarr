"""Contract-level synthetic tests for the Plan K geometry analysis seam."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research.common.geometry_analysis import (
    GeometryAnalysisCounters,
    GeometryCorpusAnalysis,
    GeometryCorpusRequest,
    GeometryIdentityAxes,
    GeometryRepresentationRoster,
    GeometryScoreBundle,
    GeometrySongRequest,
)
from scripts.embedding_research.common.threshold_analysis import (
    AnalysisEvidenceIdentity,
    SecondaryChebyshevRequest,
    analyze_secondary_all_thresholds,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db.geometry import GeometryIdentity

pytestmark = pytest.mark.unit


_IDENTITY = GeometryIdentity("song-a", "effnet", "commit-a", "geometry-v1", "profile-a")


def _song(
    song_id: str = "song-a", *, artist: str | None = "artist-a", genre: str | None = "genre-a"
) -> GeometrySongRequest:
    return GeometrySongRequest(
        song_id=song_id,
        backbone="effnet",
        geometry_identity=_IDENTITY,
        observation_evidence={"observation_group_sha256": "observation-a"},
        artist=artist,
        genre=genre,
        head_label=None,
    )


def _corpus_request(items: tuple[GeometrySongRequest, ...], *, synthetic_only: bool = True) -> GeometryCorpusRequest:
    return GeometryCorpusRequest(
        items=items,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        scoring_semantics_version=1,
        run_id="run-a",
        execution_id="execution-a",
        numerical_profile_digest="profile-a",
        synthetic_only=synthetic_only,
    )


def test_request_validation_rejects_incomplete_or_non_synthetic_inputs() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GeometrySongRequest("", "effnet", _IDENTITY, {})
    with pytest.raises(ValueError, match="synthetic-only"):
        _corpus_request((_song(),), synthetic_only=False)
    with pytest.raises(ValueError, match="threshold request"):
        GeometryCorpusRequest(
            items=(_song(),),
            threshold_request=object(),  # type: ignore[arg-type]
            experiment="temporal_global",
            evaluation_id="evaluation-a",
            scoring_semantics_version=1,
            run_id="run-a",
            execution_id="execution-a",
            numerical_profile_digest="profile-a",
        )


def test_corpus_requests_require_deterministic_unique_song_backbone_order() -> None:
    with pytest.raises(ValueError, match="deterministically ordered"):
        _corpus_request((_song("song-b"), _song("song-a")))
    with pytest.raises(ValueError, match="unique"):
        _corpus_request((_song(), _song()))
    request = _corpus_request((_song("song-a"), _song("song-b")))
    assert tuple(item.song_id for item in request.items) == ("song-a", "song-b")


def test_primary_and_chebyshev_have_separate_experiment_identity_domains() -> None:
    primary = dense_primary_threshold_request()
    secondary = SecondaryChebyshevRequest((1.0,))
    secondary_analysis = analyze_secondary_all_thresholds(
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        np.ones(2, dtype=np.uint8),
        secondary,
    )
    assert primary.experiment == "temporal_global"
    assert secondary.experiment == "temporal_perdim_chebyshev_secondary"
    assert secondary_analysis.results[0].search.experiment == secondary.experiment
    assert secondary_analysis.results[0].threshold.value == pytest.approx(1.0)
    assert primary.thresholds[70].value == pytest.approx(1.0)
    assert primary.experiment != secondary.experiment


def test_complete_identity_axes_are_required() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        AnalysisEvidenceIdentity(
            geometry_id="geometry-a",
            observation_group_sha256="observation-a",
            geometry_semantics_version="geometry-v1",
            numerical_profile_digest="profile-a",
            threshold_id="",
            structural_identity="struct-a",
            evaluation_id="evaluation-a",
            search_representation_id="search-a",
            scoring_semantics_version=1,
            execution_id="execution-a",
        )
    with pytest.raises(ValueError, match="non-empty"):
        GeometryIdentityAxes(
            geometry_id="geometry-a",
            observation_group_sha256="observation-a",
            geometry_semantics_version="geometry-v1",
            numerical_profile_digest="profile-a",
            mask_digest="mask-a",
            threshold_id="threshold-a",
            structural_identity="structural-a",
            search_representation_id="search-a",
            evaluation_id="",
            scoring_semantics_version=1,
            execution_id="execution-a",
        )


def test_artist_genre_and_head_labels_are_independently_nullable() -> None:
    request = _song(artist=None, genre=None)
    assert request.artist is None
    assert request.genre is None
    assert request.head_label is None
    assert _song(artist="artist-a", genre=None).artist == "artist-a"
    assert _song(artist=None, genre="genre-a").genre == "genre-a"


def test_result_contracts_are_finite_immutable_and_synthetic_only() -> None:
    with pytest.raises(ValueError, match="finite"):
        GeometryScoreBundle(scores={"representation-a": float("nan")})
    with pytest.raises(ValueError, match="synthetic-only"):
        GeometryCorpusAnalysis(
            run_id="run-a",
            execution_id="execution-a",
            experiment="temporal_global",
            evaluation_id="evaluation-a",
            numerical_profile_digest="profile-a",
            scoring_semantics_version=1,
            synthetic_only=False,
        )
    with pytest.raises(ValueError, match="segmentation"):
        GeometryAnalysisCounters(segmentation_from_scorer_count=1)
    assert GeometryRepresentationRoster(representations=()).unique_representation_count == 0


def test_geometry_analysis_module_rejects_non_cpu_external_ownership() -> None:
    path = Path(__file__).parents[1] / "common" / "geometry_analysis.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        import_name.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for import_name in node.names
    }
    imports.update(
        node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imports <= {"__future__", "collections", "dataclasses", "types", "typing", "numpy", "scripts"}
    source = path.read_text(encoding="utf-8").lower()
    for forbidden in ("onnx", "cuda", "torch", "audio"):
        assert forbidden not in source
    assert "synthetic-only" in source
