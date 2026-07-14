"""Classifier and ML head dataclasses used across Nomarr.

This module defines data containers for ML classifier outputs — the results
of running ONNX head models on audio embeddings, including tier thresholds,
head specifications, and per-label decisions.

Usage:
    from v2.nomarr.helpers.dataclasses.classifier_dataclass import (
        Cascade,
        HeadDecision,
        HeadSpec,
        LabelPrediction,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Cascade:
    """Tier thresholds for gating head predictions.

    Three tiers — high (strict), medium (regular), low (loose) — each defined
    by a minimum score threshold, a ratio threshold for opponent suppression,
    and a gap threshold for intra-head separation.

    Defaults are tuned for high-confidence music tagging.
    """

    high: float = 0.8
    """Minimum score for the strict (high-confidence) tier."""

    medium: float = 0.75
    """Minimum score for the regular tier."""

    low: float = 0.6
    """Minimum score for the loose (low-confidence) tier."""

    ratio_high: float = 1.2
    """Opponent ratio threshold for strict tier suppression."""

    ratio_medium: float = 1.1
    """Opponent ratio threshold for regular tier suppression."""

    ratio_low: float = 1.02
    """Opponent ratio threshold for loose tier suppression."""

    gap_high: float = 0.15
    """Intra-head gap threshold for strict tier."""

    gap_medium: float = 0.08
    """Intra-head gap threshold for regular tier."""

    gap_low: float = 0.03
    """Intra-head gap threshold for loose tier."""

    # ── Internal: (low, label_low, label_high) ────────────────────────

    regression: tuple[float, str, str] = field(
        default=(0.1, "regression_not_active", "regression_active"),
    )
    """Regression head thresholds: (min_value, label_low, label_high)."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.low <= self.medium <= self.high <= 1.0:
            raise ValueError(
                f"Cascade thresholds must satisfy 0 <= low <= medium <= high <= 1, "
                f"got low={self.low}, medium={self.medium}, high={self.high}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class HeadSpec:
    """Configuration for a single ML head model.

    Combines head metadata with runtime cascade thresholds. Constructed from
    a ``HeadInfo`` (DB-backed discovery) or filesystem-only paths.
    """

    name: str
    """Head identifier (e.g. ``"mood_happy-msd-musicnn-1"``)."""

    kind: str
    """Head type: ``"regression"``, ``"multilabel"``, or ``"multiclass"``."""

    labels: tuple[str, ...] = ()
    """Ordered label names for this head."""

    cascade: Cascade = field(default_factory=Cascade)
    """Tier thresholds for gating predictions."""

    label_thresholds: dict[str, float] = field(default_factory=dict)
    """Per-label override thresholds."""

    min_conf: float = 0.15
    """Minimum confidence (score floor) for any prediction to be emitted."""

    max_classes: int = 5
    """Maximum number of positive classes for multilabel/multiclass heads."""

    top_ratio: float = 0.5
    """Top-score ratio threshold (top class vs second-best)."""

    prob_input: bool = True
    """Whether the head expects probability-scaled inputs."""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("HeadSpec.name must not be empty")
        if self.kind not in ("regression", "multilabel", "multiclass"):
            raise ValueError(f"HeadSpec.kind must be regression/multilabel/multiclass, got {self.kind!r}")
        if self.min_conf < 0.0 or self.min_conf > 1.0:
            raise ValueError(f"HeadSpec.min_conf must be in [0, 1], got {self.min_conf}")


@dataclass(frozen=True, slots=True, kw_only=True)
class LabelPrediction:
    """Single label prediction from a classifier head.

    Produced by running a ``HeadSpec`` against pooled segment scores.
    """

    label: str
    """Label name (e.g. ``"happy"``, ``"rock"``)."""

    model_key: str
    """Deterministic model tag key (e.g. ``"happy_effnet_mood_happy-msd-musicnn-1"``)."""

    score: float
    """Post-calibration confidence score in [0, 1]."""

    tier: str | None = None
    """Tier level (``"high"``, ``"medium"``, ``"low"``) — internal only, never persisted."""

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("LabelPrediction.label must not be empty")
        if not self.model_key:
            raise ValueError("LabelPrediction.model_key must not be empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"LabelPrediction.score must be in [0, 1], got {self.score}")


@dataclass(frozen=True, slots=True, kw_only=True)
class HeadDecision:
    """Result of running one head model against pooled segment scores.

    Aggregates the head spec, all active label predictions (excluding
    suppressed opponents and below-minimum labels), and the calibration
    identifier that was applied.
    """

    head_name: str
    """Name of the head that produced these predictions."""

    head_kind: str
    """Head type: ``"regression"``, ``"multilabel"``, or ``"multiclass"``."""

    predictions: tuple[LabelPrediction, ...]
    """Active label predictions after gating and suppression."""

    calibration_id: str | None = None
    """Calibration identifier (e.g. ``"platt_1"``) or ``None`` if uncalibrated."""

    def __post_init__(self) -> None:
        if not self.head_name:
            raise ValueError("HeadDecision.head_name must not be empty")

    @property
    def has_predictions(self) -> bool:
        """``True`` when at least one label prediction passed gating."""
        return len(self.predictions) > 0

    @property
    def tier_labels(self) -> dict[str, list[str]]:
        """Group labels by tier (``"high"``, ``"medium"``, ``"low"``)."""
        result: dict[str, list[str]] = {"high": [], "medium": [], "low": []}
        for pred in self.predictions:
            if pred.tier and pred.tier in result:
                result[pred.tier].append(pred.label)
        return {k: v for k, v in result.items() if v}


@dataclass(frozen=True, slots=True, kw_only=True)
class ClassificationResult:
    """Aggregated result of running all heads on one audio file.

    Contains per-head decisions, the accumulated tag scores (before mood
    aggregation and opponent suppression), and the source file identity.
    """

    file_id: str
    """Identifier of the source audio file."""

    decisions: tuple[HeadDecision, ...]
    """Per-head decisions in processing order."""

    tag_scores: dict[str, float] = field(default_factory=dict)
    """Accumulated tag key → score map (raw, pre-mood-aggregation)."""

    def __post_init__(self) -> None:
        if not self.file_id:
            raise ValueError("ClassificationResult.file_id must not be empty")
        # Freeze mutable defaults on frozen dataclass.
        object.__setattr__(self, "tag_scores", dict(self.tag_scores))

    @classmethod
    def empty(cls, file_id: str) -> ClassificationResult:
        """Construct an empty result (no heads ran, no predictions)."""
        return cls(file_id=file_id, decisions=(), tag_scores={})
