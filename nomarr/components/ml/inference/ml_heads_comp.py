from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.tagging.tagging_aggregation_comp import (
    DEFAULT_STABILITY_THRESHOLDS,
    StabilityThresholds,
)
from nomarr.helpers.dto.ml_dto import HeadOutput

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from collections.abc import Callable

    from nomarr.helpers.dto.ml_head_dto import HeadInfo


def _as_float_list(element: Any) -> list[float]:
    if element is None:
        return []
    if isinstance(element, list | tuple | np.ndarray):
        return [float(vec_element) for vec_element in element]
    return [float(element)]


def _to_prob(vector: np.ndarray, already_prob: bool) -> np.ndarray:
    if already_prob:
        clipped: np.ndarray = np.clip(vector, 0.0, 1.0)
        return clipped
    result: np.ndarray = 1.0 / (1.0 + np.exp(-vector))
    return result


@dataclass
class Cascade:
    """Tier thresholds from the original training calibration.
    - high >= t_high (strict)
    - medium >= t_med (regular)
    - low >= t_low (loose)
    Values are in probability space [0,1].

    Note: Defaults tuned for high-confidence music tagging.
    """

    high: float = 0.8
    medium: float = 0.75
    low: float = 0.6
    ratio_high: float = 1.2
    ratio_medium: float = 1.1
    ratio_low: float = 1.02
    gap_high: float = 0.15
    gap_medium: float = 0.08
    gap_low: float = 0.03


@dataclass
class HeadSpec:
    """Specification for a single head model used by decision and pipeline functions."""

    name: str
    kind: str
    labels: list[str] = field(default_factory=list)
    cascade: Cascade = field(default_factory=Cascade)
    label_thresholds: dict[str, float] = field(default_factory=dict)
    min_conf: float = 0.15
    max_classes: int = 5
    top_ratio: float = 0.5
    prob_input: bool = True

    @classmethod
    def from_head_info(cls, hi: HeadInfo) -> HeadSpec:
        """Build a :class:`HeadSpec` from a :class:`HeadInfo` (DB-backed path)."""
        return cls(
            name=hi.name,
            kind=hi.head_type,
            labels=list(hi.labels),
        )


def decide_regression(values: np.ndarray, labels: list[str]) -> dict[str, float]:
    """Return raw float outputs keyed by label; preserves full precision."""
    out: dict[str, float] = {}
    for i, lab in enumerate(labels):
        try:
            out[lab] = float(values[i])
        except Exception as e:
            logger.debug("[ml_heads] Failed to cast regression output for label %r at index %d: %s", lab, i, e)
            continue
    return out


def _find_counter_confidence(
    label: str,
    label_idx: int,
    probs: np.ndarray,
    label_to_idx: dict[str, int],
    num_labels: int,
) -> float:
    """Find counter-confidence for a label.

    Resolution order:
    1. Explicit 'non_*' or 'not_*' negation label → use its probability.
    2. Binary head (exactly 2 labels) → use the other label's probability.
    3. Fallback → use the highest probability among all *other* labels in this head.
       This ensures ratio/gap remain meaningful even for labels without explicit
       negation partners, preventing them from auto-clearing tier gates.
    """
    non_name = f"non_{label}"
    not_name = f"not_{label}"
    if non_name in label_to_idx:
        return float(probs[label_to_idx[non_name]])
    if not_name in label_to_idx:
        return float(probs[label_to_idx[not_name]])
    if num_labels == 2:
        other_idx = 1 - label_idx
        if other_idx < len(probs):
            return float(probs[other_idx])
    # Fallback: second-best (max of all other labels) as counter-confidence.
    # For single-label heads (degenerate), return 0.0.
    if num_labels <= 1:
        return 0.0
    best_other = 0.0
    for idx in range(min(num_labels, len(probs))):
        if idx != label_idx:
            val = float(probs[idx])
            best_other = max(best_other, val)
    return best_other


def _determine_tier(
    prob: float,
    ratio: float,
    gap: float,
    cascade: Cascade,
    *,
    label_std: float | None = None,
    stability_thresholds: StabilityThresholds | None = None,
) -> str | None:
    """Determine tier (high/medium/low) based on cascade thresholds.

    If label_std is provided (segment-level standard deviation), unstable predictions
    are downgraded based on stability_thresholds:
    - std >= acceptable: no tier (too unreliable to trust)
    - std >= stable: cap at "low" tier maximum
    - std >= very_stable: cap at "medium" tier maximum

    Args:
        prob: Probability score for the label
        ratio: Ratio of label probability to counter-label probability
        gap: Gap between label and counter-label probabilities
        cascade: Cascade thresholds from model sidecar
        label_std: Optional segment-level standard deviation for stability gating
        stability_thresholds: Thresholds for stability gating (default: DEFAULT_STABILITY_THRESHOLDS)

    Returns:
        Tier string ("high", "medium", "low") or None if no tier requirements are met.

    """
    if stability_thresholds is None:
        stability_thresholds = DEFAULT_STABILITY_THRESHOLDS

    # Stability ceiling: segment variance caps the maximum achievable tier.
    max_tier_rank = 3  # 3=high, 2=medium, 1=low
    if label_std is not None:
        if label_std >= stability_thresholds.acceptable:
            return None  # Too unstable to assign any tier
        if label_std >= stability_thresholds.stable:
            max_tier_rank = 1  # Cap at low
        elif label_std >= stability_thresholds.very_stable:
            max_tier_rank = 2  # Cap at medium

    if max_tier_rank >= 3 and prob >= cascade.high and ratio >= cascade.ratio_high and gap >= cascade.gap_high:
        return "high"
    if max_tier_rank >= 2 and prob >= cascade.medium and ratio >= cascade.ratio_medium and gap >= cascade.gap_medium:
        return "medium"
    if prob >= cascade.low and ratio >= cascade.ratio_low and gap >= cascade.gap_low:
        return "low"
    return None


def decide_multilabel(
    scores: np.ndarray,
    spec: HeadSpec,
    *,
    segment_std: np.ndarray | None = None,
) -> dict[str, Any]:
    """Multilabel: select all labels with score >= (per-label threshold or cascade.low).

    Also provide tier mapping (high/medium/low) per selected label.

    Returns ALL labels with their probabilities, but only assigns tiers to labels
    that meet the cascade thresholds (confidence, ratio, gap).

    If segment_std is provided (per-label standard deviation across segments),
    it is used to gate tier assignment: labels with high segment variance get
    their tier downgraded or rejected, matching the stability gating already
    used for regression heads.
    """
    probs = _to_prob(scores, already_prob=spec.prob_input)
    out: dict[str, Any] = {}
    all_probs: dict[str, float] = {}
    label_to_idx = {lab: idx for idx, lab in enumerate(spec.labels)}
    eps = 1e-09
    for i, lab in enumerate(spec.labels):
        prob = float(probs[i]) if i < len(probs) else 0.0
        all_probs[lab] = prob
        if prob < spec.min_conf:
            continue
        thr = spec.label_thresholds.get(lab, spec.cascade.low)
        if prob < thr:
            continue
        counter_p = _find_counter_confidence(lab, i, probs, label_to_idx, len(spec.labels))
        counter_p = max(0.0, min(1.0, counter_p))
        ratio = prob / max(counter_p, eps)
        gap = prob - counter_p
        # Extract per-label segment std if available
        lab_std: float | None = None
        if segment_std is not None and i < len(segment_std):
            lab_std = float(segment_std[i])
        tier = _determine_tier(prob, ratio, gap, spec.cascade, label_std=lab_std)
        if tier is None and prob >= 0.1:
            std_info = f", std={lab_std:.3f}" if lab_std is not None else ""
            logger.debug(
                f"[heads] Label '{lab}' rejected: p={prob:.3f} (need >={spec.cascade.low:.2f}), "
                f"ratio={ratio:.2f} (need >={spec.cascade.ratio_low:.2f}), "
                f"gap={gap:.3f} (need >={spec.cascade.gap_low:.2f}){std_info}",
            )
        if tier is not None:
            out[lab] = {"p": prob, "tier": tier}
    return {"selected": out, "all_probs": all_probs}


def decide_binary_multiclass(
    scores: np.ndarray,
    spec: HeadSpec,
    *,
    segment_std: np.ndarray | None = None,
) -> dict[str, Any]:
    """Binary multiclass (2-class softmax): uses the model's native counter-confidence.

    For 2-class softmax heads (e.g., happy/non_happy), each label's counter-confidence
    is the other label's probability — directly from the model output, no heuristics.
    Otherwise identical to decide_multilabel: same cascade, ratio, gap, and stability
    gating logic.

    Returns ALL labels with their probabilities, but only assigns tiers to labels
    that meet the cascade thresholds (confidence, ratio, gap).
    """
    probs = _to_prob(scores, already_prob=spec.prob_input)
    out: dict[str, Any] = {}
    all_probs: dict[str, float] = {}
    n_labels = len(spec.labels)
    eps = 1e-09
    for i, lab in enumerate(spec.labels):
        prob = float(probs[i]) if i < len(probs) else 0.0
        all_probs[lab] = prob
        if prob < spec.min_conf:
            continue
        thr = spec.label_thresholds.get(lab, spec.cascade.low)
        if prob < thr:
            continue
        # Native counter-confidence: the other class in the softmax pair
        if n_labels == 2:
            other_idx = 1 - i
            counter_p = float(probs[other_idx]) if other_idx < len(probs) else 0.0
        else:
            # N>2 multiclass: highest probability among all other classes
            counter_p = 0.0
            for j in range(min(n_labels, len(probs))):
                if j != i:
                    counter_p = max(counter_p, float(probs[j]))
        counter_p = max(0.0, min(1.0, counter_p))
        ratio = prob / max(counter_p, eps)
        gap = prob - counter_p
        # Extract per-label segment std if available
        lab_std: float | None = None
        if segment_std is not None and i < len(segment_std):
            lab_std = float(segment_std[i])
        tier = _determine_tier(prob, ratio, gap, spec.cascade, label_std=lab_std)
        if tier is None and prob >= 0.1:
            std_info = f", std={lab_std:.3f}" if lab_std is not None else ""
            logger.debug(
                f"[heads] Label '{lab}' rejected: p={prob:.3f} (need >={spec.cascade.low:.2f}), "
                f"ratio={ratio:.2f} (need >={spec.cascade.ratio_low:.2f}), "
                f"gap={gap:.3f} (need >={spec.cascade.gap_low:.2f}){std_info}",
            )
        if tier is not None:
            out[lab] = {"p": prob, "tier": tier}
    return {"selected": out, "all_probs": all_probs}


class HeadDecision:
    """A lightweight container for the decision of a single head."""

    def __init__(self, head: HeadSpec, details: dict[str, Any], all_probs: dict[str, float] | None = None) -> None:
        self.head = head
        self.details = details
        self.all_probs = all_probs or {}

    def as_tags(self, prefix: str = "", key_builder: Callable[[str], str] | None = None) -> dict[str, Any]:
        """Produce a flat tag dict with numeric values only.

        Tier information is preserved in self.details but not emitted as *_tier tags.
        Use HeadOutput objects to access tier information for aggregation.

        Args:
            prefix: Legacy simple prefix (e.g., "yamnet_")
            key_builder: Optional function(label) -> versioned_key for modern tag naming

        """
        tags: dict[str, Any] = {}
        if head_is_regression(self.head):
            for key, value in self.details.items():
                tag_key = key_builder(key) if key_builder else f"{prefix}{key}"
                tags[tag_key] = value
            return tags
        for key, value in self.details.items():
            tag_key = key_builder(key) if key_builder else f"{prefix}{key}"
            tags[tag_key] = float(value.get("p", 0.0))
        for lab, prob in (self.all_probs or {}).items():
            tag_key = key_builder(lab) if key_builder else f"{prefix}{lab}"
            if tag_key not in tags:
                tags[tag_key] = float(prob)
        return tags

    def to_head_outputs(
        self,
        head_info: HeadInfo,
        prefix: str = "",
        key_builder: Callable[[str], str] | None = None,
    ) -> list[HeadOutput]:
        """Convert HeadDecision to list of HeadOutput objects.

        For multilabel heads, creates one HeadOutput per selected label with tier information.
        For multiclass heads, creates HeadOutput objects for emitted labels with tiers from
        the adaptive decision function.
        For regression heads, this should not be called (regression uses add_regression_mood_tiers).

        Args:
            head_info: HeadInfo providing label and tag key metadata
            prefix: Legacy simple prefix (fallback)
            key_builder: Optional function(label) -> versioned_key

        Returns:
            List of HeadOutput objects

        """
        outputs: list[HeadOutput] = []
        if head_is_regression(self.head):
            return outputs
        for label, value in self.details.items():
            if key_builder:
                tag_key = key_builder(label)
                _, calibration_id = head_info.build_versioned_tag_key(label)
            else:
                tag_key = f"{prefix}{label}"
                calibration_id = None
            if isinstance(value, dict):
                prob = float(value.get("p", 0.0))
                tier = value.get("tier")
            else:
                prob = float(value)
                tier = None
            outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=tag_key,
                    label=label,
                    value=prob,
                    tier=tier,
                    calibration_id=calibration_id,
                ),
            )
        for label, prob in self.all_probs.items():
            if label in self.details:
                continue
            if key_builder:
                tag_key = key_builder(label)
                _, calibration_id = head_info.build_versioned_tag_key(label)
            else:
                tag_key = f"{prefix}{label}"
                calibration_id = None
            outputs.append(
                HeadOutput(
                    head=head_info,
                    model_key=tag_key,
                    label=label,
                    value=float(prob),
                    tier=None,
                    calibration_id=calibration_id,
                ),
            )
        return outputs


def head_is_regression(spec: HeadSpec) -> bool:
    """Return True if the head spec represents a regression head."""
    return "regression" in spec.kind.lower()


def head_is_multiclass(spec: HeadSpec) -> bool:
    """Return True if the head spec represents a multiclass head."""
    return "multiclass" in spec.kind.lower() or "multi-class" in spec.kind.lower()


def run_head_decision(
    spec: HeadSpec,
    scores: np.ndarray,
    *,
    prefix: str = "",
    emit_all_scores: bool = True,
    segment_std: np.ndarray | None = None,
) -> HeadDecision:
    """Turn the raw output vector for a head into a :class:`HeadDecision`.

    Args:
        spec: Head specification describing labels, thresholds, and cascade.
        scores: Head outputs (logits or probabilities).
        prefix: Optional string to prepend to tag keys.
        emit_all_scores: (unused, kept for signature compat).
        segment_std: Optional per-label segment standard deviation
            for stability gating.
    """
    kind = spec.kind.lower()
    vec = np.asarray(scores).reshape(-1)
    if "regression" in kind:
        details = decide_regression(vec, spec.labels)
        return HeadDecision(spec, details)
    if "multiclass" in kind or "multi-class" in kind:
        result = decide_binary_multiclass(vec, spec, segment_std=segment_std)
        details = result.get("selected", {})
        all_probs = result.get("all_probs", {})
        return HeadDecision(spec, details, all_probs)
    result = decide_multilabel(vec, spec, segment_std=segment_std)
    details = result.get("selected", {})
    all_probs = result.get("all_probs", {})
    return HeadDecision(spec, details, all_probs)
