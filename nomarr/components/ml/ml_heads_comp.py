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

    from nomarr.components.ml.ml_discovery_comp import Sidecar


def _safe_get(data_dict: dict[str, Any], *keys, default=None):
    """Return first matching key present in dict d (top-level), else default."""
    for key in keys:
        if key in data_dict:
            return data_dict[key]
    return default


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

    @classmethod
    def from_sidecar(cls, sc: Sidecar, fallback: Cascade | None = None) -> Cascade:
        meta = sc.data or {}
        levels = _safe_get(meta, "cascade", "tiers", default=None)
        if isinstance(levels, dict):
            return cls(
                high=float(levels.get("high", fallback.high if fallback else 0.8)),
                medium=float(levels.get("medium", fallback.medium if fallback else 0.6)),
                low=float(levels.get("low", fallback.low if fallback else 0.4)),
                ratio_high=float(levels.get("ratio_high", getattr(fallback, "ratio_high", 1.25) if fallback else 1.25)),
                ratio_medium=float(
                    levels.get("ratio_medium", getattr(fallback, "ratio_medium", 1.15) if fallback else 1.15),
                ),
                ratio_low=float(levels.get("ratio_low", getattr(fallback, "ratio_low", 1.05) if fallback else 1.05)),
                gap_high=float(levels.get("gap_high", getattr(fallback, "gap_high", 0.2) if fallback else 0.2)),
                gap_medium=float(levels.get("gap_medium", getattr(fallback, "gap_medium", 0.1) if fallback else 0.1)),
                gap_low=float(levels.get("gap_low", getattr(fallback, "gap_low", 0.05) if fallback else 0.05)),
            )
        if isinstance(levels, list | tuple) and len(levels) >= 3:
            return cls(high=float(levels[0]), medium=float(levels[1]), low=float(levels[2]))
        return fallback or cls()


@dataclass
class HeadSpec:
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
    def from_sidecar(cls, sc: Sidecar) -> HeadSpec:
        meta = sc.data or {}
        head_name = str(_safe_get(meta, "head_name", "name") or "head")
        head_type = str(_safe_get(meta, "head_type", "type") or "multilabel")
        labels = _safe_get(meta, "classes", "labels", default=[]) or []
        labels = [str(x) for x in labels]
        cascade = Cascade.from_sidecar(sc)
        thresh_dict = _safe_get(meta, "label_thresholds", "thresholds", default={}) or {}
        if isinstance(thresh_dict, list):
            thresh_dict = {labels[i]: float(v) for i, v in enumerate(thresh_dict) if i < len(labels)}
        elif isinstance(thresh_dict, dict):
            thresh_dict = {str(k): float(v) for k, v in thresh_dict.items()}
        else:
            thresh_dict = {}
        min_conf = float(_safe_get(meta, "min_conf", "min_confidence", default=0.15) or 0.15)
        max_classes = int(_safe_get(meta, "max_classes", "top_k_cap", default=5) or 5)
        top_ratio = float(_safe_get(meta, "top_ratio", "top_k_ratio", default=0.5) or 0.5)
        prob_input = bool(_safe_get(meta, "prob_input", default=True))
        return cls(
            name=head_name,
            kind=head_type,
            labels=labels,
            cascade=cascade,
            label_thresholds=thresh_dict,
            min_conf=min_conf,
            max_classes=max_classes,
            top_ratio=top_ratio,
            prob_input=prob_input,
        )


def decide_regression(values: np.ndarray, labels: list[str]) -> dict[str, float]:
    """Return raw float outputs keyed by label; preserves full precision."""
    out: dict[str, float] = {}
    for i, lab in enumerate(labels):
        try:
            out[lab] = float(values[i])
        except Exception:
            continue
    return out


def _find_counter_confidence(
    label: str, label_idx: int, probs: np.ndarray, label_to_idx: dict[str, int], num_labels: int,
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
            if val > best_other:
                best_other = val
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
    scores: np.ndarray, spec: HeadSpec, *, segment_std: np.ndarray | None = None,
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
    scores: np.ndarray, spec: HeadSpec, *, segment_std: np.ndarray | None = None,
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
        self, head_info: Any, framework_version: str, prefix: str = "", key_builder: Callable[[str], str] | None = None,
    ) -> list[Any]:
        """Convert HeadDecision to list of HeadOutput objects.

        For multilabel heads, creates one HeadOutput per selected label with tier information.
        For multiclass heads, creates HeadOutput objects for emitted labels with tiers from
        the adaptive decision function.
        For regression heads, this should not be called (regression uses add_regression_mood_tiers).

        Args:
            head_info: HeadInfo object from discovery
            framework_version: Runtime Essentia version
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
                calibration_id = getattr(head_info, "calibration_id", None)
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
                    head=head_info, model_key=tag_key, label=label, value=prob, tier=tier, calibration_id=calibration_id,
                ),
            )
        for label, prob in self.all_probs.items():
            if label in self.details:
                continue
            if key_builder:
                tag_key = key_builder(label)
                calibration_id = getattr(head_info, "calibration_id", None)
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
    return "regression" in spec.kind.lower()


def head_is_multiclass(spec: HeadSpec) -> bool:
    return "multiclass" in spec.kind.lower() or "multi-class" in spec.kind.lower()


def run_head_decision(
    sc: Sidecar, scores: np.ndarray, *, prefix: str = "", emit_all_scores: bool = True,
    segment_std: np.ndarray | None = None,
) -> HeadDecision:
    """Turn the raw output vector for a head into a HeadDecision.
    - sc: Sidecar describing the head (labels, thresholds, cascade)
    - scores: head outputs (logits or probs depending on sidecar)
    - prefix: optional string to prepend to tag keys (e.g., "yamnet_").
    - segment_std: optional per-label segment standard deviation for stability gating.
    """
    spec = HeadSpec.from_sidecar(sc)
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
