from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from scripts.embedding_research.common.threshold_analysis import (
    PRIMARY_EXPERIMENT,
    PRIMARY_EXPERIMENT_VERSION,
    SECONDARY_EXPERIMENT,
    PrimaryThresholdRequest,
    SecondaryChebyshevRequest,
    analyze_all_thresholds,
    analyze_secondary_all_thresholds,
    dense_primary_threshold_request,
    primary_experiment_manifest,
    validate_secondary_chebyshev_request,
)
from scripts.embedding_research.db.geometry import GeometryIdentity, GeometryRecord
from scripts.embedding_research.helpers.gram_segmentation import gram_from_stream


def _record() -> GeometryRecord:
    stream = np.asarray([[1, 0], [0.9, 0.2], [0, 1], [-1, 0]], dtype=np.float32)
    gram, blob = gram_from_stream(stream)
    identity = GeometryIdentity("song", "effnet", "commit", "geometry-v1", "profile")
    return GeometryRecord(identity, "geometry", {"mask_payload_sha256": "mask"}, blob, gram)


def test_experiment_one_manifest_is_exact_and_not_configurable() -> None:
    manifest = primary_experiment_manifest()
    assert manifest["experiment"] == PRIMARY_EXPERIMENT
    assert manifest["experiment_version"] == PRIMARY_EXPERIMENT_VERSION
    assert manifest["threshold_count"] == 171
    assert manifest["threshold_indices"] == tuple(range(171))
    assert manifest["threshold_values"][0] == float(np.float32(0.30))
    assert manifest["threshold_values"][-1] == float(np.float32(2.00))
    assert len(set(manifest["threshold_values"])) == 171


def test_dense_request_is_exact_indexed_float32_grid() -> None:
    request = dense_primary_threshold_request()
    assert request == PrimaryThresholdRequest(tuple(range(171)))
    assert len(request.thresholds) == 171
    assert tuple(item.index for item in request.thresholds) == tuple(range(171))
    assert request.thresholds[0].value == float(np.float32(0.30))
    assert request.thresholds[-1].value == float(np.float32(np.float32(0.30) + np.float32(170) * np.float32(0.01)))
    assert len({item.threshold_id for item in request.thresholds}) == 171


def test_primary_request_rejects_non_dense_indices_and_secondary_is_explicit() -> None:
    with pytest.raises(ValueError):
        PrimaryThresholdRequest((0, 1))
    secondary = SecondaryChebyshevRequest((0.3, 0.4))
    assert validate_secondary_chebyshev_request(secondary) is secondary
    with pytest.raises(ValueError):
        validate_secondary_chebyshev_request(dense_primary_threshold_request())
    with pytest.raises(ValueError):
        SecondaryChebyshevRequest((-0.1,))


def test_secondary_dispatch_is_coordinate_only_and_keeps_identity_domain() -> None:
    stream = np.asarray([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
    analysis = analyze_secondary_all_thresholds(
        stream,
        np.ones(3, dtype=np.uint8),
        SecondaryChebyshevRequest((1.0, np.nextafter(np.float32(1.0), np.float32(0.0)))),
    )
    assert analysis.experiment == SECONDARY_EXPERIMENT
    assert analysis.geometry_decode_count == 0
    assert analysis.mask_validation_count == 1
    assert tuple(result.threshold.index for result in analysis.results) == (0, 1)
    assert all(result.search.experiment == SECONDARY_EXPERIMENT for result in analysis.results)
    with pytest.raises(ValueError):
        analyze_all_thresholds(_record(), np.ones(4, dtype=np.uint8), SecondaryChebyshevRequest((1.0,)))


def test_analysis_decodes_once_validates_mask_once_and_never_gathers() -> None:
    analysis = analyze_all_thresholds(_record(), np.ones(4, dtype=np.uint8), dense_primary_threshold_request())
    assert analysis.experiment == PRIMARY_EXPERIMENT
    assert len(analysis.results) == 171
    assert tuple(result.threshold.index for result in analysis.results) == tuple(range(171))
    assert analysis.geometry_decode_count == 1
    assert analysis.mask_validation_count == 1
    assert analysis.stream_gather_count == 0
    assert analysis.segmentation_from_scorer_count == 0
    assert all(result.structural.identity != result.search.search_representation_id for result in analysis.results)


def test_analysis_requires_exact_binary_mask() -> None:
    with pytest.raises(ValueError):
        analyze_all_thresholds(_record(), np.ones(3, dtype=np.uint8), dense_primary_threshold_request())
    with pytest.raises(ValueError):
        analyze_all_thresholds(_record(), np.asarray([1, 2, 0, 1], dtype=np.uint8), dense_primary_threshold_request())


def test_transient_classes_canonicalize_lowest_index_and_keep_modes_separate() -> None:
    analysis = analyze_all_thresholds(_record(), np.ones(4, dtype=np.uint8), dense_primary_threshold_request())
    classes = analysis.representation_classes
    assert classes
    assert all(item.canonical_threshold_index == item.member_threshold_indices[0] for item in classes)
    assert all(item.member_threshold_indices == tuple(sorted(item.member_threshold_indices)) for item in classes)
    assert analysis.unique_representation_count == len(analysis.unique_search_representations)

    result = analysis.results[0]
    secondary = replace(
        result,
        search=replace(result.search, experiment=SECONDARY_EXPERIMENT),
    )
    mixed = replace(analysis, results=(result, secondary))
    assert mixed.unique_representation_count == 2
    assert {item.member_threshold_indices for item in mixed.representation_classes} == {(0,), (0,)}


def test_transient_class_rejects_non_lowest_canonical() -> None:
    from scripts.embedding_research.common.threshold_analysis import SearchRepresentationClass

    with pytest.raises(ValueError):
        SearchRepresentationClass(("key",), 3, (3, 4, 2))
