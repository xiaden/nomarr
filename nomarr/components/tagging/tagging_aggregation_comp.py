"""Tag aggregation logic — mood tiers and conflict resolution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

from nomarr.components.ml.onnx.ml_known_models_comp import OPPONENT_MAP
from nomarr.components.tagging.mood_labels_comp import MOOD_MAPPING
from nomarr.helpers.dto.ml_dto import HeadOutput
from nomarr.helpers.dto.tagging_dto import BuildTierTermSetsResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StabilityThresholds:
    """Thresholds for stability-based tier gating.

    These thresholds control how segment-level variance affects tier assignment:
    - acceptable: Max std for any tier (above this = no tier)
    - stable: Max std for medium tier (above this = cap at low)
    - very_stable: Max std for high tier (above this = cap at medium)
    """

    acceptable: float = 0.25
    stable: float = 0.15
    very_stable: float = 0.08


# Default stability thresholds (used by ML inference and reconstruction)
DEFAULT_STABILITY_THRESHOLDS = StabilityThresholds()


@dataclass(frozen=True)
class RegressionThresholds:
    """Thresholds for regression head mood classification.

    These thresholds determine when regression values (0-1 intensity) trigger mood terms:
    - strong: Threshold for high-intensity label (>= this value)
    - weak: Threshold for low-intensity label (<= this value)
    - Values between weak and strong are neutral (both labels emitted with no tier)
    """

    strong: float = 0.7
    weak: float = 0.3


# Default regression thresholds
DEFAULT_REGRESSION_THRESHOLDS = RegressionThresholds()


# ---------------------------------------------------------------------------
# Regression mood tier assignment
# ---------------------------------------------------------------------------


def assign_regression_outputs(
    head_info: Any,
    head_name: str,
    mean_val: float,
    std_val: float,
    stability_thresholds: StabilityThresholds,
    regression_thresholds: RegressionThresholds,
    log_prefix: str = "aggregation",
    applied_calibration_id: str | None = None,
) -> list[HeadOutput]:
    """Shared regression-to-HeadOutput conversion used by both inference and reconstruction.

    Given a clamped mean and std for a regression head, determines the mood term,
    assigns a stability-based tier, and returns the corresponding HeadOutput(s).

    For the neutral case (mean between weak and strong thresholds), both the high
    and low terms are emitted with tier=None.

    Args:
        head_info: HeadInfo object for the regression head
        head_name: The head name key into MOOD_MAPPING
        mean_val: Clamped [0, 1] regression mean
        std_val: Standard deviation (optionally calibration-scaled)
        stability_thresholds: Thresholds for stability gating
        regression_thresholds: Thresholds for mood determination
        log_prefix: Logging prefix tag (e.g. "aggregation" or "reconstruction")
        applied_calibration_id: Calibration ID string to record on each HeadOutput.
            When provided (non-None), reflects that calibration was applied to the values.
            When None, records that no calibration was applied.

    Returns:
        List of HeadOutput objects (1 for decisive, 2 for neutral)

    """
    if head_name not in MOOD_MAPPING:
        return []

    high_term, low_term = MOOD_MAPPING[head_name]
    is_high = mean_val >= regression_thresholds.strong
    is_low = mean_val <= regression_thresholds.weak

    # Neutral case: emit both terms with no tier
    if not is_high and not is_low:
        model_key_high, _key_calib_id_high = head_info.build_versioned_tag_key(
            high_term,
            calib_method="none",
            calib_version=0,
        )
        model_key_low, _key_calib_id_low = head_info.build_versioned_tag_key(
            low_term,
            calib_method="none",
            calib_version=0,
        )
        effective_calib_id_high = applied_calibration_id if applied_calibration_id is not None else _key_calib_id_high
        effective_calib_id_low = applied_calibration_id if applied_calibration_id is not None else _key_calib_id_low
        logger.debug(
            "[%s] Regression neutral: %s \u2192 both %s/%s (mean=%.3f, std=%.3f)",
            log_prefix,
            head_name,
            high_term,
            low_term,
            mean_val,
            std_val,
        )
        return [
            HeadOutput(
                head=head_info,
                model_key=model_key_high,
                label=high_term,
                value=mean_val,
                tier=None,
                calibration_id=effective_calib_id_high,
            ),
            HeadOutput(
                head=head_info,
                model_key=model_key_low,
                label=low_term,
                value=1.0 - mean_val,
                tier=None,
                calibration_id=effective_calib_id_low,
            ),
        ]

    # Decisive case: pick one term and assign tier via stability gating
    mood_term = high_term if is_high else low_term
    model_key, _key_calib_id = head_info.build_versioned_tag_key(
        mood_term,
        calib_method="none",
        calib_version=0,
    )
    effective_calib_id = applied_calibration_id if applied_calibration_id is not None else _key_calib_id

    tier: str | None = None
    if std_val >= stability_thresholds.acceptable:
        logger.debug(
            "[%s] Regression no tier: %s \u2192 %s (mean=%.3f, std=%.3f - high variance)",
            log_prefix,
            head_name,
            mood_term,
            mean_val,
            std_val,
        )
    else:
        intensity = abs(mean_val - 0.5) * 2
        if std_val < stability_thresholds.very_stable and intensity >= 0.8:
            tier = "high"
        elif std_val < stability_thresholds.stable and intensity >= 0.6:
            tier = "medium"
        else:
            tier = "low"
        logger.debug(
            "[%s] Regression mood: %s \u2192 %s (mean=%.3f, std=%.3f, intensity=%.2f, tier=%s)",
            log_prefix,
            head_name,
            mood_term,
            mean_val,
            std_val,
            intensity,
            tier,
        )

    return [
        HeadOutput(
            head=head_info,
            model_key=model_key,
            label=mood_term,
            value=mean_val,
            tier=tier,
            calibration_id=effective_calib_id,
        ),
    ]


# ---------------------------------------------------------------------------
# Public API: regression inference entry point
# ---------------------------------------------------------------------------


def add_regression_mood_tiers(
    regression_heads: list[tuple[Any, list[float]]],
    stability_thresholds: StabilityThresholds | None = None,
    regression_thresholds: RegressionThresholds | None = None,
) -> list[Any]:
    """Convert regression head predictions (approachability, engagement) into HeadOutput objects.

    Uses versioned tag keys from HeadInfo.build_versioned_tag_key() instead of hardcoded prefixes.

    Regression heads output INTENSITY values (0-1), not probabilities:
    - High values (>= strong threshold) indicate STRONG presence of the attribute
    - Low values (<= weak threshold) indicate STRONG presence of the opposite attribute
    - Middle values are neutral/ambiguous

    ALWAYS creates a HeadOutput with the mean value (clamped to [0, 1]).
    Variance only affects TIER assignment:
    - High variance \u2192 no tier (unreliable measurement)
    - Low variance + extreme value \u2192 tier assigned based on confidence

    Args:
        regression_heads: List of (HeadInfo, segment_values) tuples for regression heads
        stability_thresholds: Thresholds for stability gating (default: DEFAULT_STABILITY_THRESHOLDS)
        regression_thresholds: Thresholds for regression mood determination (default: DEFAULT_REGRESSION_THRESHOLDS)

    Returns:
        List of HeadOutput objects with tier information

    """
    if not regression_heads:
        return []

    if stability_thresholds is None:
        stability_thresholds = DEFAULT_STABILITY_THRESHOLDS
    if regression_thresholds is None:
        regression_thresholds = DEFAULT_REGRESSION_THRESHOLDS

    outputs: list[HeadOutput] = []
    for head_info, segment_values in regression_heads:
        head_name = head_info.name
        if not segment_values or head_name not in MOOD_MAPPING:
            continue
        arr = np.array(segment_values)
        mean_val = float(np.mean(arr))
        std_val = float(np.std(arr))
        mean_val = max(0.0, min(1.0, mean_val))

        outputs.extend(
            assign_regression_outputs(
                head_info,
                head_name,
                mean_val,
                std_val,
                stability_thresholds=stability_thresholds,
                regression_thresholds=regression_thresholds,
                log_prefix="aggregation",
            ),
        )
    return outputs


# ---------------------------------------------------------------------------
# Mood aggregation pipeline
# ---------------------------------------------------------------------------


def _build_tier_map(
    head_outputs: list[Any],
) -> dict[str, tuple[str, float, str]]:
    """Build tier map from HeadOutput objects.

    Note: Calibration should be applied BEFORE creating HeadOutput objects
    (in reconstruct_head_outputs_from_stats). This function only builds
    the tier map from pre-calibrated outputs.

    Args:
        head_outputs: List of HeadOutput objects (values should already be calibrated)

    Returns:
        Dictionary mapping model_key -> (tier, value, label)

    """
    mood_outputs = [ho for ho in head_outputs if ho.tier is not None]
    logger.debug("[aggregation] %s mood outputs with tiers", len(mood_outputs))
    if not mood_outputs:
        logger.debug("[aggregation] No mood outputs with tiers, returning empty mood tags")
        return {}
    tier_map: dict[str, tuple[str, float, str]] = {}
    for ho in mood_outputs:
        tier_map[ho.model_key] = (ho.tier, ho.value, ho.label)
    logger.debug("[aggregation] Tier map has %s entries", len(tier_map))
    return tier_map


def _compute_suppressed_keys(
    head_outputs: list[HeadOutput],
    opponent_map: dict[str, set[str]],
) -> set[str]:
    """Identify conflicting mood outputs and return model keys to suppress.

    Two suppression cases are handled:

    1. **Intra-head**: multiple tiered outputs sharing the *same* head instance
       (structurally rare for binary classifiers but handled defensively).
       Keep the strongest; suppress the rest.

    2. **Cross-head**: tiered outputs from *different* head instances whose
       labels are semantic opponents per the derived opponent map (e.g.
       ``"aggressive"`` from ``mood_aggressive`` vs ``"relaxed"`` from
       ``mood_relaxed``).  Suppress both sides to avoid contradictory tags.

    Args:
        head_outputs: All HeadOutput objects (tiered and non-tiered).
        opponent_map: Label -> set of opponent labels, derived from
            ``KNOWN_MODELS`` via :data:`OPPONENT_MAP`.

    Returns:
        Set of ``model_key`` strings to suppress.

    """
    _tier_rank: dict[str, int] = {
        "high": 3, "strict": 3, "medium": 2, "norm": 2, "normal": 2, "low": 1,
    }
    tiered = [ho for ho in head_outputs if ho.tier is not None]
    suppressed: set[str] = set()

    # --- Intra-head pass -------------------------------------------------
    by_head: dict[int, list[HeadOutput]] = {}
    for ho in tiered:
        key = id(ho.head)
        by_head.setdefault(key, []).append(ho)

    for group in by_head.values():
        if len(group) <= 1:
            continue
        best = max(group, key=lambda ho: (_tier_rank.get(ho.tier or "", 0), ho.value))
        for ho in group:
            if ho is not best:
                suppressed.add(ho.model_key)
                logger.debug(
                    "[aggregation] Intra-head suppress: %s (%s) loses to %s (%s)",
                    ho.model_key, ho.tier, best.model_key, best.tier,
                )

    # --- Cross-head pass -------------------------------------------------
    active = [ho for ho in tiered if ho.model_key not in suppressed]
    for i, ho_a in enumerate(active):
        if ho_a.model_key in suppressed:
            continue
        for ho_b in active[i + 1 :]:
            if ho_b.model_key in suppressed:
                continue
            if id(ho_a.head) == id(ho_b.head):
                continue  # Same head — already handled above
            if ho_b.label in opponent_map.get(ho_a.label, set()):
                suppressed.add(ho_a.model_key)
                suppressed.add(ho_b.model_key)
                logger.debug(
                    "[aggregation] Cross-head suppress: %s (%s) vs %s (%s) — semantic conflict",
                    ho_a.model_key, ho_a.label, ho_b.model_key, ho_b.label,
                )

    return suppressed


def _build_tier_term_sets(
    tier_map: dict[str, tuple[str, float, str]],
    suppressed_keys: set[str],
) -> BuildTierTermSetsResult:
    """Build strict, regular, and loose term sets from tier map.

    Labels in ``tier_map`` are already human-readable display terms (set at
    inference time from ``KNOWN_MODELS``), so no additional label remapping
    is needed.

    Args:
        tier_map: Dictionary mapping model_key -> (tier, value, label)
        suppressed_keys: Set of keys to skip due to conflicts

    Returns:
        BuildTierTermSetsResult with strict_terms, regular_terms, loose_terms

    """
    strict_terms: set[str] = set()
    regular_terms: set[str] = set()
    loose_terms: set[str] = set()
    for model_key, (tier, value, label) in tier_map.items():
        if model_key in suppressed_keys:
            continue
        logger.debug("[aggregation] Adding %s=%.3f (%s) to tier '%s'", model_key, value, label, tier)
        if tier in ("high", "strict"):
            strict_terms.add(label)
        elif tier in ("medium", "norm", "normal"):
            regular_terms.add(label)
        else:
            loose_terms.add(label)
    logger.debug(
        "[aggregation] Mood aggregation: strict=%s, regular=%s, loose=%s",
        len(strict_terms),
        len(regular_terms),
        len(loose_terms),
    )
    return BuildTierTermSetsResult(strict_terms=strict_terms, regular_terms=regular_terms, loose_terms=loose_terms)


def _make_inclusive_mood_tags(strict_terms: set[str], regular_terms: set[str], loose_terms: set[str]) -> dict[str, Any]:
    """Build final mood tag dictionary with inclusive tier expansion.

    Implements: strict \u2282 regular \u2282 loose

    Args:
        strict_terms: Set of strict tier terms
        regular_terms: Set of regular tier terms
        loose_terms: Set of loose tier terms

    Returns:
        Dictionary containing mood-strict, mood-regular, mood-loose tags

    """
    if strict_terms:
        regular_terms |= strict_terms
        loose_terms |= strict_terms
    if regular_terms:
        loose_terms |= regular_terms
    result: dict[str, Any] = {}
    if strict_terms:
        result["mood-strict"] = sorted(strict_terms)
    if regular_terms:
        result["mood-regular"] = sorted(regular_terms)
    if loose_terms:
        result["mood-loose"] = sorted(loose_terms)
    return result


def aggregate_mood_tiers(
    head_outputs: list[Any],
) -> dict[str, Any]:
    r"""Aggregate HeadOutput objects into mood-strict, mood-regular, mood-loose collections.

    Uses HeadOutput.tier to determine confidence level instead of parsing \*_tier tags.

    Calibration should be applied BEFORE calling this function, typically in
    reconstruct_head_outputs_from_stats() or during live inference.

    Applies pair conflict suppression: if both sides of a pair (e.g., happy/sad,
    aggressive/relaxed) have tiers, neither is emitted to avoid contradictory tags.

    Also applies label improvements for better human readability.

    Args:
        head_outputs: List of HeadOutput objects with tier information (pre-calibrated)

    Returns:
        Dictionary containing mood-strict, mood-regular, mood-loose tags

    """
    logger.debug(
        "[aggregation] aggregate_mood_tiers called with %s HeadOutput objects",
        len(head_outputs),
    )
    tier_map = _build_tier_map(head_outputs)
    if not tier_map:
        return {}
    suppressed_keys = _compute_suppressed_keys(head_outputs, OPPONENT_MAP)
    tier_sets = _build_tier_term_sets(tier_map, suppressed_keys)
    return _make_inclusive_mood_tags(tier_sets.strict_terms, tier_sets.regular_terms, tier_sets.loose_terms)



def collect_mood_outputs(
    regression_heads: list[tuple[Any, list[float]]],
    all_head_outputs: list[Any],
) -> dict[str, Any]:
    r"""Collect and aggregate all mood outputs from classification and regression heads.

    Combines regression-based HeadOutput objects with classification head outputs,
    then aggregates them into mood tier tag dictionaries.

    Args:
        regression_heads: List of (HeadInfo, segment_values) tuples for regression heads.
        all_head_outputs: List of HeadOutput objects from classification heads
            (mutated in place by appending regression outputs).

    Returns:
        Dict of mood-\* tag strings for the file.

    """
    regression_outputs = add_regression_mood_tiers(regression_heads)
    all_head_outputs.extend(regression_outputs)
    logger.debug("[aggregation] Total HeadOutput objects: %d", len(all_head_outputs))
    return aggregate_mood_tiers(all_head_outputs)
