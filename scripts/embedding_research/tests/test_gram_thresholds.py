"""R7 — exact 171-threshold grid, default experiment identity, secondary non-collapse.

The default grid is exactly ``t_i = float32(0.30 + i * 0.01)`` for ``i`` in 0..170 and
cannot be widened by config; the secondary Chebyshev experiment can never collapse with
the primary temporal-global representations because experiment is part of the key.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.common import threshold_analysis as ta
from scripts.embedding_research.common.threshold_analysis import (
    PRIMARY_EXPERIMENT,
    PRIMARY_THRESHOLD_COUNT,
    PRIMARY_THRESHOLD_END,
    PRIMARY_THRESHOLD_START,
    PRIMARY_THRESHOLD_STEP,
    SECONDARY_EXPERIMENT,
    AllThresholdAnalysis,
    PrimaryThresholdRequest,
    SearchRepresentation,
    StructuralIdentity,
    ThresholdAnalysisResult,
    ThresholdSpec,
    collapse_search_representations,
    primary_experiment_manifest,
)
from scripts.embedding_research.tests._gram_evidence import emit_evidence


def _search(*, experiment: str, index: int) -> SearchRepresentation:
    return SearchRepresentation(
        structural_identity="structural-1",
        medoid_source_indices=(0,),
        searchable_weights=(1.0,),
        total_searchable=1,
        geometry_id="geometry-1",
        observation_group_sha256="observation-1",
        profile_digest="profile-1",
        mask_digest="mask-1",
        scoring_semantics_version=1,
        experiment=experiment,
        search_representation_id=f"rep-{experiment}-{index}",
    )


def _result(*, experiment: str, index: int) -> ThresholdAnalysisResult:
    spec = ThresholdSpec(index, float(index), f"{experiment}:threshold:{index}")
    structural = StructuralIdentity(spec.threshold_id, index, ((0, 1),), ((),), f"structural-{index}")
    return ThresholdAnalysisResult(
        spec, structural, _search(experiment=experiment, index=index), search_projection=None
    )


def test_exact_171_threshold_grid() -> None:
    request = PrimaryThresholdRequest.dense_default()
    assert tuple(spec.index for spec in request.thresholds) == tuple(range(PRIMARY_THRESHOLD_COUNT))
    for index, spec in enumerate(request.thresholds):
        expected = float(np.float32(PRIMARY_THRESHOLD_START + np.float32(np.float32(index) * PRIMARY_THRESHOLD_STEP)))
        assert spec.value == expected, f"threshold index {index} value drifted"
    assert request.thresholds[0].value == float(np.float32(0.30))
    assert request.thresholds[-1].value == float(np.float32(2.00))
    values = [spec.value for spec in request.thresholds]
    assert values == sorted(values)
    assert len({spec.threshold_id for spec in request.thresholds}) == 171

    with pytest.raises(ValueError):
        PrimaryThresholdRequest((0, 1, 2))
    with pytest.raises(ValueError):
        PrimaryThresholdRequest(tuple(range(171)), experiment=SECONDARY_EXPERIMENT)
    emit_evidence(
        "r7-exact-171-grid.json",
        {
            "count": len(values),
            "start": values[0],
            "end": values[-1],
            "step": float(PRIMARY_THRESHOLD_STEP),
            "first_id": request.thresholds[0].threshold_id,
            "last_id": request.thresholds[-1].threshold_id,
        },
    )


def test_default_report_identity() -> None:
    manifest = primary_experiment_manifest()
    assert manifest["experiment"] == PRIMARY_EXPERIMENT
    assert manifest["experiment_version"] == "experiment_one_v1"
    assert manifest["threshold_indices"] == tuple(range(171))
    assert manifest["threshold_count"] == 171
    assert manifest["threshold_start"] == float(PRIMARY_THRESHOLD_START)
    assert manifest["threshold_step"] == float(PRIMARY_THRESHOLD_STEP)
    assert manifest["threshold_end"] == float(PRIMARY_THRESHOLD_END)
    assert manifest["threshold_values"] == tuple(
        spec.value for spec in PrimaryThresholdRequest.dense_default().thresholds
    )
    emit_evidence(
        "r7-default-report-identity.json",
        {
            "experiment": manifest["experiment"],
            "experiment_version": manifest["experiment_version"],
            "threshold_count": manifest["threshold_count"],
            "threshold_start": manifest["threshold_start"],
            "threshold_end": manifest["threshold_end"],
        },
    )


def test_chebyshev_does_not_collapse_global() -> None:
    primary = _search(experiment=PRIMARY_EXPERIMENT, index=0)
    secondary = _search(experiment=SECONDARY_EXPERIMENT, index=0)
    assert ta._search_representation_key(primary) != ta._search_representation_key(secondary)

    analysis = AllThresholdAnalysis(
        experiment=PRIMARY_EXPERIMENT,
        geometry_id="geometry-1",
        observation_group_sha256="observation-1",
        profile_digest="profile-1",
        mask_digest="mask-1",
        results=(
            _result(experiment=PRIMARY_EXPERIMENT, index=0),
            _result(experiment=SECONDARY_EXPERIMENT, index=0),
        ),
        geometry_semantics_version="gram-ptc-v1",
        evaluation_id="evaluation-1",
        execution_id="execution-1",
    )
    classes = collapse_search_representations(analysis)
    assert len(classes) == 2, "primary and secondary must not collapse into one class"
    experiments = {ta._search_representation_key(item.search)[0] for item in analysis.results}
    assert experiments == {PRIMARY_EXPERIMENT, SECONDARY_EXPERIMENT}

    with pytest.raises(ValueError):
        ta.analyze_all_thresholds(
            object(),
            np.ones(1, dtype=np.uint8),
            PrimaryThresholdRequest.dense_default(),
            experiment=SECONDARY_EXPERIMENT,
        )
    emit_evidence(
        "r7-secondary-non-collapse.json",
        {"class_count": len(classes), "experiments": sorted(experiments), "collapsed": False},
    )
