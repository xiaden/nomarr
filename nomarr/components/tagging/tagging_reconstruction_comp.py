"""Reconstruct HeadOutput objects from stored segment statistics.

Re-creates the ML inference outputs without running models, using numeric tags
and per-segment statistics stored in the database. Applies optional calibration
before tier assignment so the reconstructed outputs match what live inference
would produce.

This is a COMPONENT — it contains heavy domain logic (calibration math,
classification decision functions, regression tier assignment) even though
the work *feels* like orchestration. The function coordinates multiple
component-level operations but never touches IO, services, or workflows.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from nomarr.components.ml.ml_calibration_comp import apply_minmax_calibration
from nomarr.components.ml.ml_heads_comp import (
    HeadSpec,
    decide_binary_multiclass,
    decide_multilabel,
    head_is_multiclass,
)
from nomarr.components.tagging.mood_labels_comp import normalize_tag_label
from nomarr.components.tagging.tagging_aggregation_comp import (
    DEFAULT_REGRESSION_THRESHOLDS,
    DEFAULT_STABILITY_THRESHOLDS,
    RegressionThresholds,
    StabilityThresholds,
    assign_regression_outputs,
)
from nomarr.helpers.dto.ml_dto import HeadOutput

logger = logging.getLogger(__name__)


def reconstruct_head_outputs_from_stats(
    numeric_tags: dict[str, float],
    segment_stats_by_head: dict[str, list[dict[str, Any]]],
    head_infos: list[Any],
    framework_version: str,
    calibrations: dict[str, dict[str, Any]] | None = None,
    stability_thresholds: StabilityThresholds | None = None,
    regression_thresholds: RegressionThresholds | None = None,
) -> list[Any]:
    """Reconstruct HeadOutput objects from segment statistics and numeric tags.

    Uses the same tier logic as ML inference to ensure identical mood tag results.
    For classification heads, applies decide_multilabel with segment std.
    For regression heads, delegates to assign_regression_outputs (shared with
    add_regression_mood_tiers) after applying optional calibration.

    When calibrations are provided, they are applied to raw probability/mean values
    BEFORE tier assignment. This ensures tiers reflect calibrated confidence levels
    (p5\u21920, p95\u21921 normalization) rather than raw model outputs.

    Args:
        numeric_tags: Dict of tag_key -> value from DB. Keys have the namespace prefix
            already stripped (e.g. "happy_essentia21b..." not "nom:happy_essentia21b...").
        segment_stats_by_head: Dict of head_name -> label_stats [{label, mean, std, min, max}, ...]
        head_infos: List of discovered HeadInfo objects
        framework_version: Runtime Essentia version
        calibrations: Optional calibration data (model_key -> {p5, p95, method}).
            When provided, raw values are normalized before tier logic runs.
        stability_thresholds: Thresholds for stability gating (default: DEFAULT_STABILITY_THRESHOLDS)
        regression_thresholds: Thresholds for regression mood determination (default: DEFAULT_REGRESSION_THRESHOLDS)

    Returns:
        List of HeadOutput objects with tier information matching ML inference

    """
    if stability_thresholds is None:
        stability_thresholds = DEFAULT_STABILITY_THRESHOLDS
    if regression_thresholds is None:
        regression_thresholds = DEFAULT_REGRESSION_THRESHOLDS

    all_outputs: list[HeadOutput] = []

    for head_info in head_infos:
        head_name = head_info.name
        if head_name not in segment_stats_by_head:
            logger.debug("[reconstruction] No segment stats for %s, skipping", head_name)
            continue

        label_stats = segment_stats_by_head[head_name]
        stats_by_label = {stat["label"]: stat for stat in label_stats}

        if head_info.is_regression_head:
            if not label_stats:
                continue
            stat = label_stats[0]
            raw_mean = stat["mean"]
            raw_std = stat["std"]

            # Apply calibration to regression mean BEFORE tier logic
            reg_label = stat["label"]
            calib_scale = 1.0
            if calibrations and reg_label in calibrations:
                calib_data = calibrations[reg_label]
                mean_val = apply_minmax_calibration(raw_mean, calib_data)
                p5, p95 = calib_data.get("p5", 0.0), calib_data.get("p95", 1.0)
                span = p95 - p5
                if span > 0:
                    calib_scale = 1.0 / span
            else:
                mean_val = raw_mean

            std_val = raw_std * calib_scale
            mean_val = max(0.0, min(1.0, mean_val))

            all_outputs.extend(
                assign_regression_outputs(
                    head_info,
                    head_name,
                    mean_val,
                    std_val,
                    framework_version=framework_version,
                    stability_thresholds=stability_thresholds,
                    regression_thresholds=regression_thresholds,
                    log_prefix="reconstruction",
                ),
            )
        else:
            # Classification head: reconstruct from numeric tags + segment std
            spec = HeadSpec.from_sidecar(head_info.sidecar)
            is_multiclass = head_is_multiclass(spec)

            probs = np.zeros(len(spec.labels), dtype=np.float32)
            segment_std_array = np.zeros(len(spec.labels), dtype=np.float32)

            for i, label in enumerate(spec.labels):
                norm_label = normalize_tag_label(label)
                model_key, _ = head_info.build_versioned_tag_key(
                    norm_label,
                    framework_version=framework_version,
                    calib_method="none",
                    calib_version=0,
                )
                calib_scale = 1.0
                if model_key in numeric_tags:
                    raw_prob = numeric_tags[model_key]
                    if calibrations and norm_label in calibrations:
                        calib_data = calibrations[norm_label]
                        probs[i] = apply_minmax_calibration(raw_prob, calib_data)
                        p5, p95 = calib_data.get("p5", 0.0), calib_data.get("p95", 1.0)
                        span = p95 - p5
                        if span > 0:
                            calib_scale = 1.0 / span
                    else:
                        probs[i] = raw_prob

                if label in stats_by_label:
                    raw_std = stats_by_label[label]["std"]
                    segment_std_array[i] = raw_std * calib_scale

            if is_multiclass:
                result = decide_binary_multiclass(probs, spec, segment_std=segment_std_array)
                selected = result.get("selected", {})
                all_probs_dict = result.get("all_probs", {})
            else:
                result = decide_multilabel(probs, spec, segment_std=segment_std_array)
                selected = result.get("selected", {})
                all_probs_dict = result.get("all_probs", {})

            def _build_key(lbl: str, head: Any = head_info) -> str:
                norm_lbl = normalize_tag_label(lbl)
                model_key, _ = head.build_versioned_tag_key(
                    norm_lbl,
                    framework_version=framework_version,
                    calib_method="none",
                    calib_version=0,
                )
                return str(model_key)

            for label, value_dict in selected.items():
                prob = float(value_dict.get("p", 0.0))
                tier_val = value_dict.get("tier")
                model_key = _build_key(label)
                all_outputs.append(
                    HeadOutput(
                        head=head_info,
                        model_key=model_key,
                        label=label,
                        value=prob,
                        tier=tier_val,
                        calibration_id=None,
                    ),
                )

            for label, prob in all_probs_dict.items():
                if label in selected:
                    continue
                model_key = _build_key(label)
                all_outputs.append(
                    HeadOutput(
                        head=head_info,
                        model_key=model_key,
                        label=label,
                        value=float(prob),
                        tier=None,
                        calibration_id=None,
                    ),
                )

    logger.debug("[reconstruction] Reconstructed %s HeadOutput objects from stats", len(all_outputs))
    return all_outputs
