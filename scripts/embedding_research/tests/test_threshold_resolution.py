"""Unit tests for the pure threshold-resolution contract (Plan A P2-S1).

The contract is the spec: ``ThresholdResolution`` is immutable and finite;
``resolve_threshold`` defaults to ``direct_l2`` (``effective == configured``
exactly, no calibration record); ``std_scaled`` is an explicit opt-in that
*requires* an explicit calibration basis and records that basis plus the
computed effective value.  Non-finite and invalid inputs are rejected.  These
assertions are not weakened to make the code pass.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    STD_SCALED,
    ThresholdResolution,
    resolve_threshold,
)

_P50 = {"statistic": "p50", "value": 0.8}


# ── direct_l2 default ──────────────────────────────────────────────────────────


def test_direct_l2_is_default_and_effective_equals_configured() -> None:
    """resolve_threshold with no semantics opts to direct_l2; effective == configured exactly."""
    configured = 1.25
    res = resolve_threshold(configured)
    assert res.semantics == DIRECT_L2
    assert res.effective == configured
    assert res.configured == configured
    # Exact equality (same float, no arithmetic).
    assert res.effective is res.configured or res.effective == res.configured


def test_direct_l2_accepts_zero_and_small_configured() -> None:
    """Any finite configured value is allowed under direct_l2."""
    for value in (0.0, 0.05, 1.5):
        res = resolve_threshold(value)
        assert res.effective == value
        assert res.configured == value


def test_direct_l2_records_no_calibration_record() -> None:
    """direct_l2 returns an empty/None calibration_record (no calibration basis)."""
    res = resolve_threshold(1.0)
    assert res.calibration_record is None


def test_direct_l2_supplied_calibration_record_is_omitted() -> None:
    """A calibration record is semantically meaningless for a direct distance and is omitted."""
    res = resolve_threshold(1.0, calibration_record=_P50)
    assert res.calibration_record is None
    assert res.effective == 1.0


def test_direct_l2_explicit_is_identical_to_default() -> None:
    """Passing semantics='direct_l2' explicitly matches the default behaviour."""
    assert resolve_threshold(1.3, semantics="direct_l2").effective == 1.3


# ── std_scaled explicit computation ───────────────────────────────────────────


def test_std_scaled_computes_effective_from_explicit_basis() -> None:
    """std_scaled requires an explicit basis and computes configured x basis."""
    res = resolve_threshold(1.25, semantics="std_scaled", calibration_record=_P50)
    assert res.semantics == STD_SCALED
    assert res.effective == pytest.approx(1.25 * 0.8)
    assert res.configured == 1.25


def test_std_scaled_records_calibration_basis_and_effective() -> None:
    """The resolution records the calibration basis (as read-only) and the computed effective."""
    res = resolve_threshold(2.0, semantics="std_scaled", calibration_record=_P50)
    # effective recorded: configured x p50 basis
    assert res.effective == pytest.approx(1.6)
    assert res.calibration_record is not None
    assert res.calibration_record["statistic"] == "p50"
    assert res.calibration_record["value"] == pytest.approx(0.8)


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


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_reject_non_finite_calibration_basis_value(bad: float) -> None:
    """A non-finite std_scaled calibration basis value is rejected."""
    with pytest.raises(ValueError):
        resolve_threshold(
            1.0,
            semantics="std_scaled",
            calibration_record={"statistic": "p50", "value": bad},
        )


@pytest.mark.parametrize("zeroish", [0.0, -0.0])
def test_reject_nonpositive_calibration_basis_value(zeroish: float) -> None:
    """A zero/negative calibration basis cannot be a usable distance multiplier."""
    with pytest.raises(ValueError):
        resolve_threshold(1.0, semantics="std_scaled", calibration_record={"statistic": "p50", "value": zeroish})


def test_reject_std_scaled_without_calibration_record() -> None:
    """std_scaled without an explicit calibration basis is rejected (no silent fallback)."""
    with pytest.raises(ValueError, match="std_scaled requires an explicit calibration_record"):
        resolve_threshold(1.0, semantics="std_scaled")


def test_reject_std_scaled_with_non_mapping_record() -> None:
    """std_scaled rejects a non-Mapping calibration_record."""
    with pytest.raises(TypeError):
        resolve_threshold(1.0, semantics="std_scaled", calibration_record=[1.0])


def test_reject_std_scaled_record_without_statistic_label() -> None:
    """std_scaled requires the basis to be identified by a statistic label."""
    with pytest.raises(ValueError, match="statistic"):
        resolve_threshold(1.0, semantics="std_scaled", calibration_record={"value": 0.5})


def test_reject_unknown_semantics() -> None:
    """Unknown semantics labels are rejected."""
    with pytest.raises(ValueError, match="Unknown threshold semantics"):
        resolve_threshold(1.0, semantics="std_times_p50")


# ── immutability / finite guarantees at construction ──────────────────────────


def test_resolution_is_immutable() -> None:
    """Attempted mutation of a resolution field raises."""
    res = resolve_threshold(1.0)
    with pytest.raises(FrozenInstanceError):
        res.configured = 99.0  # type: ignore[misc]


def test_resolution_calibration_record_is_read_only() -> None:
    """The recorded calibration basis is a read-only mapping (attempted mutation raises)."""
    res = resolve_threshold(1.0, semantics="std_scaled", calibration_record=_P50)
    with pytest.raises(TypeError):
        res.calibration_record["value"] = 99.0  # type: ignore[index]


def test_direct_construction_rejects_non_finite() -> None:
    """Constructing ThresholdResolution with a non-finite field is rejected."""
    with pytest.raises(ValueError):
        ThresholdResolution(configured=1.0, effective=float("nan"), semantics="direct_l2", calibration_record=None)


def test_direct_construction_rejects_invalid_semantics() -> None:
    """Constructing ThresholdResolution with an unknown semantics is rejected."""
    with pytest.raises(ValueError):
        ThresholdResolution(configured=1.0, effective=1.0, semantics="bogus", calibration_record=None)


def test_direct_construction_finite_guarantee_holds() -> None:
    """All numeric fields on a valid resolution are finite."""
    res = resolve_threshold(1.25, semantics="std_scaled", calibration_record=_P50)
    assert math.isfinite(res.configured)
    assert math.isfinite(res.effective)


def test_std_scaled_never_selected_implicitly() -> None:
    """std_scaled is never selected unless explicitly requested."""
    res = resolve_threshold(1.25)
    assert res.semantics == DIRECT_L2
    assert res.effective == 1.25
