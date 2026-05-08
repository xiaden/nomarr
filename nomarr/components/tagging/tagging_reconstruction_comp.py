"""Reconstruct HeadOutput objects from canonical raw output streams.

Re-creates the ML inference outputs without running models, using raw per-output
segment score streams loaded from canonical persistence. Applies optional
calibration before tier assignment so the reconstructed outputs match what live
inference would produce.

This is a COMPONENT — it contains heavy domain logic (calibration math,
classification decision functions, regression tier assignment) even though
the work *feels* like orchestration. The function coordinates multiple
component-level operations but never touches IO, services, or workflows.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from nomarr.components.ml.calibration.ml_calibration_comp import apply_minmax_calibration
from nomarr.components.ml.inference.ml_embed_comp import pool_scores
from nomarr.components.ml.inference.ml_heads_comp import (
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
from nomarr.helpers.dto.ml_dto import HeadOutput, LoadedOutputStream

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StreamStats:
    """Recomputed derived stats for one canonical output stream."""

    output_id: str
    output_index: int
    label: str
    pooled_value: float
    std_value: float


def _recompute_stream_stats(values: list[float]) -> tuple[float, float]:
    """Recompute pooled value and std from a raw canonical stream."""
    values_1d = np.asarray([float(value) for value in values], dtype=np.float32)
    if values_1d.size == 0:
        return (0.0, 0.0)

    segment_matrix = values_1d.reshape(-1, 1)
    pooled = float(pool_scores(segment_matrix, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")[0])
    std = float(np.std(values_1d, dtype=np.float32))
    return (pooled, std)


def _calibration_scale(calib_data: dict[str, Any] | None) -> float:
    """Return the scale factor that calibration applies to standard deviation."""
    if calib_data is None:
        return 1.0

    p5 = float(calib_data.get("p5", 0.0))
    p95 = float(calib_data.get("p95", 1.0))
    span = p95 - p5
    if span <= 0:
        return 1.0
    return 1.0 / span


def _build_model_key(head_info: Any, label: str) -> str:
    """Build a versioned model key from authoritative HeadInfo metadata."""
    norm_label = normalize_tag_label(label)
    model_key, _ = head_info.build_versioned_tag_key(
        norm_label,
        calib_method="none",
        calib_version=0,
    )
    return str(model_key)


def _group_streams_by_head(output_streams: list[LoadedOutputStream]) -> dict[str, list[LoadedOutputStream]]:
    """Group enriched loaded output streams by head and deterministic output order."""
    grouped: dict[str, list[LoadedOutputStream]] = defaultdict(list)
    for stream in output_streams:
        grouped[stream.head_name].append(stream)

    for head_streams in grouped.values():
        head_streams.sort(key=lambda stream: (stream.output_index, stream.output_id))
    return grouped


def _resolve_stream_label(head_info: Any, stream: LoadedOutputStream) -> str | None:
    """Resolve the authoritative label for one stream from discovered head metadata."""
    if 0 <= stream.output_index < len(head_info.labels):
        resolved_label = str(head_info.labels[stream.output_index])
        if stream.label != resolved_label:
            logger.debug(
                "[reconstruction] Stream label mismatch for %s[%s]: joined=%s head_info=%s; using head metadata",
                head_info.name,
                stream.output_index,
                stream.label,
                resolved_label,
            )
        return resolved_label

    if stream.label:
        return stream.label

    logger.debug(
        "[reconstruction] Stream %s for %s has output_index=%s outside discovered labels; skipping",
        stream.output_id,
        head_info.name,
        stream.output_index,
    )
    return None


def _recompute_head_stream_stats(
    head_info: Any,
    streams: list[LoadedOutputStream],
) -> list[_StreamStats]:
    """Recompute pooled values and stds for every stream in one head."""
    stats: list[_StreamStats] = []
    for stream in streams:
        label = _resolve_stream_label(head_info, stream)
        if label is None:
            continue

        pooled_value, std_value = _recompute_stream_stats(stream.values)
        stats.append(
            _StreamStats(
                output_id=stream.output_id,
                output_index=stream.output_index,
                label=label,
                pooled_value=pooled_value,
                std_value=std_value,
            )
        )

    stats.sort(key=lambda stat: (stat.output_index, stat.output_id))
    return stats


def reconstruct_head_outputs_from_streams(
    output_streams: list[LoadedOutputStream],
    head_infos: list[Any],
    calibrations: dict[str, dict[str, Any]] | None = None,
    stability_thresholds: StabilityThresholds | None = None,
    regression_thresholds: RegressionThresholds | None = None,
) -> list[Any]:
    """Reconstruct HeadOutput objects from canonical raw output streams.

    No legacy `segment_scores_stats` fallback is provided. Classification heads
    pool per-output stream values into a probability vector and derive their
    stability vector from the recomputed per-output standard deviation. Regression
    heads use the single output stream's recomputed mean/std and reuse the live
    tier logic through `assign_regression_outputs()`.

    Args:
        output_streams: Enriched canonical stream records already joined back to
            output metadata (head, output index, label, values).
        head_infos: List of discovered HeadInfo objects.
        calibrations: Optional calibration data (`normalized_label -> calibration`).
        stability_thresholds: Thresholds for stability gating.
        regression_thresholds: Thresholds for regression mood determination.

    Returns:
        List of HeadOutput objects with tier information matching ML inference.

    """
    if stability_thresholds is None:
        stability_thresholds = DEFAULT_STABILITY_THRESHOLDS
    if regression_thresholds is None:
        regression_thresholds = DEFAULT_REGRESSION_THRESHOLDS

    grouped_streams = _group_streams_by_head(output_streams)
    all_outputs: list[HeadOutput] = []

    for head_info in head_infos:
        head_name = head_info.name
        if head_name not in grouped_streams:
            logger.debug("[reconstruction] No output streams for %s, skipping", head_name)
            continue

        stream_stats = _recompute_head_stream_stats(head_info, grouped_streams[head_name])
        if not stream_stats:
            continue

        if head_info.is_regression_head:
            stat = stream_stats[0]
            if len(stream_stats) > 1:
                logger.debug(
                    "[reconstruction] Regression head %s had %s streams; using first ordered stream only",
                    head_name,
                    len(stream_stats),
                )

            raw_mean = stat.pooled_value
            raw_std = stat.std_value
            reg_label = normalize_tag_label(stat.label)
            calib_data = calibrations.get(reg_label) if calibrations else None
            calib_scale = _calibration_scale(calib_data)
            applied_calibration_id: str | None = None

            if calib_data is not None:
                mean_val = apply_minmax_calibration(raw_mean, calib_data)
                applied_calibration_id = f"minmax_{calib_data.get('calibration_def_hash')}"
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
                    stability_thresholds=stability_thresholds,
                    regression_thresholds=regression_thresholds,
                    log_prefix="reconstruction",
                    applied_calibration_id=applied_calibration_id,
                ),
            )
            continue

        spec = HeadSpec.from_head_info(head_info)
        is_multiclass = head_is_multiclass(spec)
        probs = np.zeros(len(spec.labels), dtype=np.float32)
        segment_std_array = np.zeros(len(spec.labels), dtype=np.float32)
        calibration_ids_by_norm_label: dict[str, str | None] = {}

        for stat in stream_stats:
            if not 0 <= stat.output_index < len(spec.labels):
                logger.debug(
                    "[reconstruction] Output index %s out of range for %s; skipping stream %s",
                    stat.output_index,
                    head_name,
                    stat.output_id,
                )
                continue

            label = str(spec.labels[stat.output_index])
            norm_label = normalize_tag_label(label)
            label_calib = calibrations.get(norm_label) if calibrations else None
            if label_calib is not None:
                probs[stat.output_index] = apply_minmax_calibration(stat.pooled_value, label_calib)
                calibration_ids_by_norm_label[norm_label] = f"minmax_{label_calib.get('calibration_def_hash')}"
            else:
                probs[stat.output_index] = stat.pooled_value

            segment_std_array[stat.output_index] = stat.std_value * _calibration_scale(label_calib)

        if is_multiclass:
            result = decide_binary_multiclass(probs, spec, segment_std=segment_std_array)
            selected = result.get("selected", {})
            all_probs_dict = result.get("all_probs", {})
        else:
            result = decide_multilabel(probs, spec, segment_std=segment_std_array)
            selected = result.get("selected", {})
            all_probs_dict = result.get("all_probs", {})

        for label, value_dict in selected.items():
            prob = float(value_dict.get("p", 0.0))
            tier_val = value_dict.get("tier")
            model_key = _build_model_key(head_info, label)
            all_outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=model_key,
                    label=label,
                    value=prob,
                    tier=tier_val,
                    calibration_id=calibration_ids_by_norm_label.get(normalize_tag_label(label)),
                ),
            )

        for label, prob in all_probs_dict.items():
            if label in selected:
                continue
            model_key = _build_model_key(head_info, label)
            all_outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=model_key,
                    label=label,
                    value=float(prob),
                    tier=None,
                    calibration_id=calibration_ids_by_norm_label.get(normalize_tag_label(label)),
                ),
            )

    logger.debug("[reconstruction] Reconstructed %s HeadOutput objects from streams", len(all_outputs))
    return all_outputs


def reconstruct_head_outputs_from_stats(
    *,
    output_streams: list[LoadedOutputStream],
    head_infos: list[Any],
    calibrations: dict[str, dict[str, Any]] | None = None,
    stability_thresholds: StabilityThresholds | None = None,
    regression_thresholds: RegressionThresholds | None = None,
) -> list[Any]:
    """Compatibility alias for the stream-based reconstruction API.

    Despite the historical name, this function reconstructs only from canonical
    raw output streams. There is no segment-stats fallback.
    """
    return reconstruct_head_outputs_from_streams(
        output_streams=output_streams,
        head_infos=head_infos,
        calibrations=calibrations,
        stability_thresholds=stability_thresholds,
        regression_thresholds=regression_thresholds,
    )
