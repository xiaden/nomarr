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
    build_geometry_corpus_request,
)
from scripts.embedding_research.common.threshold_analysis import (
    AnalysisEvidenceIdentity,
    SecondaryChebyshevRequest,
    analyze_secondary_all_thresholds,
    dense_primary_threshold_request,
)
from scripts.embedding_research.db.geometry import GeometryIdentity
from scripts.embedding_research.db.geometry_profile import GeometryProfile

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


def test_request_validation_accepts_explicit_empirical_mode() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GeometrySongRequest("", "effnet", _IDENTITY, {})
    request = _corpus_request((_song(),), synthetic_only=False)
    assert request.synthetic_only is False
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


def test_result_contracts_are_finite_and_immutable() -> None:
    with pytest.raises(ValueError, match="finite"):
        GeometryScoreBundle(scores={"representation-a": float("nan")})
    empirical = GeometryCorpusAnalysis(
        run_id="run-a",
        execution_id="execution-a",
        experiment="temporal_global",
        evaluation_id="evaluation-a",
        numerical_profile_digest="profile-a",
        scoring_semantics_version=1,
        synthetic_only=False,
    )
    assert empirical.synthetic_only is False
    assert empirical.evidence_mode == "synthetic_fixture"  # direct DTO default remains fixture-scoped
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
    assert imports <= {"__future__", "collections", "dataclasses", "hashlib", "types", "typing", "numpy", "scripts"}
    source = path.read_text(encoding="utf-8").lower()
    for forbidden in ("onnx", "cuda", "torch", "audio"):
        assert forbidden not in source
    assert "synthetic-only" in source


@pytest.mark.unit
def test_empirical_request_builder_uses_head_store_and_never_synthetic_substitution(monkeypatch) -> None:
    from scripts.embedding_research.common import geometry_analysis

    calls: list[tuple[str, str]] = []

    class _HeadStore:
        output_root = Path("/synthetic/head-store")

    class _Selection:
        class _Record:
            head_ids = "alpha,beta"

        class _Marker:
            head_set_fingerprint = "head-set-digest"

        record = _Record()
        marker = _Marker()

    monkeypatch.setattr(
        "scripts.embedding_research.streams.heads_current.resolve_current_head_suite",
        lambda _root, song_id, backbone: calls.append((song_id, backbone)) or _Selection(),
    )
    monkeypatch.setattr(
        "scripts.embedding_research.streams.records.parse_head_ids", lambda value: tuple(value.split(","))
    )
    monkeypatch.setattr(geometry_analysis, "_selected_geometry_items", lambda _con, _songs, _backs: ())
    request = geometry_analysis.build_geometry_corpus_request(
        object(),
        stream_store=object(),
        profile=GeometryProfile.current(),
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="eval",
        run_id="run",
        execution_id="exec",
        scoring_semantics_version=1,
        head_store=_HeadStore(),
        synthetic_only=False,
    )
    assert request.synthetic_only is False
    assert request.items == ()
    assert calls == []

    with pytest.raises(ValueError, match="current head store"):
        geometry_analysis.build_geometry_corpus_request(
            object(),
            stream_store=object(),
            profile=GeometryProfile.current(),
            threshold_request=dense_primary_threshold_request(),
            experiment="temporal_global",
            evaluation_id="eval",
            run_id="run",
            execution_id="exec",
            scoring_semantics_version=1,
            synthetic_only=False,
        )


def test_builder_populates_empirical_frozen_head_evidence_and_keeps_fixture_mode_explicit(monkeypatch) -> None:
    from types import SimpleNamespace

    from scripts.embedding_research.common import geometry_analysis
    from scripts.embedding_research.common.head_ruler_labels import HeadSongLabel

    profile = GeometryProfile.current()
    identity = GeometryIdentity("song-a", "effnet", "observation-a", "geometry-v1", profile.digest)
    record = SimpleNamespace(evidence={"mask_payload_sha256": "mask-a"})
    song = {"song_id": "song-a", "artist": "artist-a", "genre": "genre-a", "head_label": ("fixture",)}
    monkeypatch.setattr(geometry_analysis, "_selected_geometry_items", lambda *_args: ((song, "effnet"),))
    monkeypatch.setattr(geometry_analysis, "_committed_geometry_observation", lambda *_args: (object(), identity))
    monkeypatch.setattr(geometry_analysis, "verify_geometry_current", lambda *_args, **_kwargs: record)

    class HeadStore:
        output_root = Path("/empirical/head-store")

    label = HeadSongLabel(
        song_id="song-a",
        backbone="effnet",
        full_tuple=(("gender", 1), ("timbre", 0)),
        labels=("male", "bright"),
        pooled=(0.8, 0.2),
        searchable_rows=3,
        head_set_fingerprint="heads-a",
        head_ids="gender,timbre",
        dim_by_head="gender:2,timbre:2",
        stream_ref="stream-a",
        stream_digest="stream-digest-a",
        mask_ref="mask-a",
        mask_digest="mask-digest-a",
        present=True,
    )
    calls: list[tuple[str, str, str]] = []

    def _resolve(*, head_store, song_id, backbone, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append((str(head_store.output_root), song_id, backbone))
        return label

    monkeypatch.setattr(geometry_analysis, "resolve_head_ruler_labels", _resolve)
    empirical = build_geometry_corpus_request(
        object(),
        stream_store=object(),
        profile=profile,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="eval",
        run_id="run",
        execution_id="exec",
        scoring_semantics_version=1,
        head_store=HeadStore(),
        synthetic_only=False,
    )
    assert empirical.synthetic_only is False
    # The ruler label is the frozen ACTIVATION-DERIVED semantic tuple, never the suite name.
    assert empirical.items[0].head_label == (("gender", 1), ("timbre", 0))
    # Head-suite identity is retained SEPARATELY as provenance only.
    assert empirical.items[0].head_suite_identity == "heads-a"
    assert empirical.items[0].head_provenance is label
    assert calls == [("/empirical/head-store", "song-a", "effnet")]

    fixture = build_geometry_corpus_request(
        object(),
        stream_store=object(),
        profile=profile,
        threshold_request=dense_primary_threshold_request(),
        experiment="temporal_global",
        evaluation_id="eval",
        run_id="run",
        execution_id="exec",
        scoring_semantics_version=1,
        synthetic_only=True,
    )
    assert fixture.synthetic_only is True
    assert fixture.items[0].head_label == ("fixture",)
    assert fixture.items[0].head_suite_identity is None
    assert fixture.items[0].head_provenance is None

    def missing_evidence(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("missing empirical head evidence")

    monkeypatch.setattr(geometry_analysis, "resolve_head_ruler_labels", missing_evidence)
    with pytest.raises(RuntimeError, match="missing empirical head evidence"):
        build_geometry_corpus_request(
            object(),
            stream_store=object(),
            profile=profile,
            threshold_request=dense_primary_threshold_request(),
            experiment="temporal_global",
            evaluation_id="eval",
            run_id="run",
            execution_id="exec",
            scoring_semantics_version=1,
            head_store=HeadStore(),
            synthetic_only=False,
        )
