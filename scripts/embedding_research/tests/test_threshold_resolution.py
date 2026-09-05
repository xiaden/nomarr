"""Unit tests for the direct-L2-only threshold-resolution contract (Plan A P1-S2).

The contract is the spec: there is exactly ONE threshold semantics — a finite
DIRECT normalized-unit-vector L2 distance — so ``ThresholdResolution`` is
immutable, all its numeric fields are finite, ``semantics == "direct_l2"``, and
``effective == configured`` exactly.  ``resolve_threshold(configured)`` takes a
single positional numeric argument and rejects non-finite and non-numeric
inputs.  Scaled/calibration/p50 resolution and every second-semantics branch were
removed; requesting a ``semantics``/``calibration_record`` keyword is now a
TypeError (no such parameter exists), and there is no ``calibration_record``
field on the resolution.  ``encoder_version`` records the whole-module hash of
``helpers/thresholds.py``.  These assertions are not weakened to make code pass.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    ThresholdResolution,
    resolve_threshold,
)

# ── direct_l2: the single semantics ───────────────────────────────────────────


def test_direct_l2_effective_equals_configured() -> None:
    """resolve_threshold is direct-L2; effective == configured exactly (no arithmetic)."""
    configured = 1.25
    res = resolve_threshold(configured)
    assert res.semantics == DIRECT_L2
    assert res.semantics == "direct_l2"
    assert res.effective == configured
    assert res.configured == configured
    assert res.effective is res.configured or res.effective == res.configured


def test_accepts_zero_and_small_configured() -> None:
    """Any finite configured value is allowed under direct-L2."""
    for value in (0.0, 0.05, 1.5):
        res = resolve_threshold(value)
        assert res.effective == value
        assert res.configured == value


def test_resolution_records_encoder_version() -> None:
    """The resolution carries a non-empty encoder_version (whole-module content hash)."""
    res = resolve_threshold(1.0)
    assert isinstance(res.encoder_version, str)
    assert res.encoder_version


def test_resolution_has_no_calibration_field() -> None:
    """No calibration_record field exists on the direct-only resolution."""
    res = resolve_threshold(1.0)
    assert not hasattr(res, "calibration_record")


# ── rejections ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_reject_non_finite_configured(bad: float) -> None:
    """NaN and ±Inf configured values are rejected with ValueError."""
    with pytest.raises(ValueError):
        resolve_threshold(bad)


@pytest.mark.parametrize("bad", ["0.5", True, None, [1.0], object()])
def test_reject_invalid_configured_type(bad: object) -> None:
    """Non-numeric configured values are rejected with TypeError."""
    with pytest.raises(TypeError):
        resolve_threshold(bad)


@pytest.mark.parametrize(
    "kw",
    [
        {"semantics": "direct_l2"},
        {"semantics": "std_scaled"},
        {"calibration_record": {"statistic": "p50", "value": 0.8}},
    ],
)
def test_reject_second_semantics_or_calibration_kwargs(kw: dict) -> None:
    """There is no semantics/calibration parameter: any such keyword is a TypeError."""
    with pytest.raises(TypeError):
        resolve_threshold(1.0, **kw)  # type: ignore[arg-type]


# ── immutability / finite guarantees at construction ──────────────────────────


def test_resolution_is_immutable() -> None:
    """Attempted mutation of a resolution field raises."""
    res = resolve_threshold(1.0)
    with pytest.raises(FrozenInstanceError):
        res.configured = 99.0  # type: ignore[misc]


def test_direct_construction_rejects_non_finite() -> None:
    """Constructing ThresholdResolution with a non-finite field is rejected."""
    with pytest.raises(ValueError):
        ThresholdResolution(configured=1.0, effective=float("nan"), semantics="direct_l2", encoder_version="x")


def test_direct_construction_rejects_wrong_semantics() -> None:
    """Constructing ThresholdResolution with a non-direct_l2 semantics is rejected."""
    with pytest.raises(ValueError):
        ThresholdResolution(configured=1.0, effective=1.0, semantics="std_scaled", encoder_version="x")


def test_direct_construction_rejects_effective_not_equal_configured() -> None:
    """Constructing ThresholdResolution where effective != configured is rejected."""
    with pytest.raises(ValueError):
        ThresholdResolution(configured=1.0, effective=0.9, semantics="direct_l2", encoder_version="x")


def test_direct_construction_finite_guarantee_holds() -> None:
    """All numeric fields on a valid resolution are finite."""
    res = resolve_threshold(1.25)
    assert math.isfinite(res.configured)
    assert math.isfinite(res.effective)
