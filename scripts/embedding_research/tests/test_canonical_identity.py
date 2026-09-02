"""Unit tests for canonical numeric/text identity and config hashing (Plan A P2-S3).

These pin the deterministic identity inputs later ``seg_config`` rows consume:
fixed canonical numeric formatting (same binary float -> same text; no exponent
ambiguity; non-finite rejected), canonical text identities for threshold (with
semantics label), bin mode, outlier window, strategy version, semantics,
calibration record (basis, not object identity) and alias target, plus the
deterministic config-hash over the fixed field ordering.  Legacy on-disk cache
path encoders (``helpers.binning.threshold_key``) are intentionally untouched.
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.helpers.thresholds import (
    DIRECT_L2,
    ThresholdResolution,
    canonical_bin_mode,
    canonical_calibration_record,
    canonical_config_hash,
    canonical_config_inputs,
    canonical_float,
    canonical_int,
    canonical_outlier_window,
    canonical_semantics,
    canonical_strategy_version,
    canonical_threshold,
    canonical_threshold_of,
    resolve_threshold,
)

_P50 = {"statistic": "p50", "value": 0.8}


# ── canonical numeric formatting ──────────────────────────────────────────────


def test_canonical_float_is_deterministic() -> None:
    """The same value encodes identically every time."""
    assert canonical_float(1.25) == canonical_float(1.25)


def test_canonical_float_equivalent_spellings_identical() -> None:
    """0.1 and 1e-1 are the same double and encode identically (no spelling drift)."""
    assert canonical_float(0.1) == canonical_float(1e-1)
    assert canonical_float(0.1) == "0.1"


def test_canonical_float_has_no_exponent_ambiguity() -> None:
    """Exponent forms are expanded to fixed-point; never scientific notation."""
    assert canonical_float(1e-06) == "0.000001"
    assert "e" not in canonical_float(1e-06)
    assert "e" not in canonical_float(1.5e-05)
    assert canonical_float(1.5e-05) == "0.000015"


def test_canonical_float_round_trips_integers() -> None:
    assert canonical_float(3.0) == "3.0"
    assert canonical_float(1.0) == "1.0"


def test_canonical_float_negative_zero_normalised() -> None:
    """-0.0 is normalised to 0.0 (mathematically equal, identical encoding)."""
    assert canonical_float(-0.0) == canonical_float(0.0) == "0.0"


def test_canonical_float_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        canonical_float(float("nan"))
    with pytest.raises(ValueError):
        canonical_float(float("inf"))


def test_canonical_float_keeps_distinct_floats_distinct() -> None:
    """Two genuinely different floats never collide (no fixed-precision rounding)."""
    assert canonical_float(0.949999) != canonical_float(0.95)


def test_canonical_int_rejects_bool_and_non_int() -> None:
    assert canonical_int(3) == "3"
    with pytest.raises(TypeError):
        canonical_int(True)
    with pytest.raises(TypeError):
        canonical_int(3.0)


# ── canonical text identities ─────────────────────────────────────────────────


def test_canonical_threshold_labels_semantics() -> None:
    """The threshold identity carries configured, effective and the semantics label."""
    res = resolve_threshold(1.25)
    text = canonical_threshold(res.configured, res.effective, res.semantics)
    assert text.startswith(f"{DIRECT_L2}:configured=1.25:effective=1.25")


def test_canonical_threshold_sensitive_to_semantics() -> None:
    """direct_l2 and std_scaled of the same configured value encode differently."""
    std = resolve_threshold(1.25, semantics="std_scaled", calibration_record={"statistic": "p50", "value": 1.0})
    direct = resolve_threshold(1.25)
    assert canonical_threshold_of(std) != canonical_threshold_of(direct)


def test_canonical_calibration_record_is_basis_not_object_identity() -> None:
    """Two equal-content records serialize identically regardless of insertion order."""
    a = {"value": 0.8, "statistic": "p50"}
    b = {"statistic": "p50", "value": 0.8}
    assert canonical_calibration_record(a) == canonical_calibration_record(b)


def test_canonical_calibration_record_none_and_numeric_encoding() -> None:
    assert canonical_calibration_record(None) == "none"
    assert canonical_calibration_record({"statistic": "p50", "value": 0.8}) == "statistic=p50;value=0.8"


def test_canonical_text_helpers() -> None:
    assert canonical_bin_mode("temporal_global") == "temporal_global"
    assert canonical_outlier_window(3) == "3"
    assert canonical_strategy_version(1) == "1"
    assert canonical_semantics("direct_l2") == "direct_l2"
    with pytest.raises(ValueError):
        canonical_semantics("bogus")


def test_canonical_aliases() -> None:
    from scripts.embedding_research.helpers.thresholds import canonical_alias

    assert canonical_alias(None) == "none"
    assert canonical_alias(7) == "7"


# ── canonical config-hash ─────────────────────────────────────────────────────


def test_config_hash_is_deterministic() -> None:
    kwargs = {
        "backbone": "effnet",
        "bin_mode": "temporal_global",
        "threshold_configured": 1.25,
        "threshold_effective": 1.25,
        "semantics": "direct_l2",
    }
    assert canonical_config_hash(**kwargs) == canonical_config_hash(**kwargs)


def test_config_hash_same_for_equivalent_numeric_spellings() -> None:
    """0.1 and 1e-1 are the same float, so a config using either hashes identically."""
    a = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=0.1,
        threshold_effective=0.1,
        semantics="direct_l2",
    )
    b = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1e-1,
        threshold_effective=1e-1,
        semantics="direct_l2",
    )
    assert a == b


def test_config_hash_sensitive_to_semantics_label() -> None:
    """direct_l2 and std_scaled with identical values hash differently."""
    direct = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1.25,
        threshold_effective=1.25,
        semantics="direct_l2",
    )
    std = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1.25,
        threshold_effective=1.0,
        semantics="std_scaled",
        calibration_record=_P50,
    )
    assert direct != std


def test_config_hash_sensitive_to_calibration_record() -> None:
    """Two std_scaled configs with different calibration bases hash differently."""
    a = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1.25,
        threshold_effective=1.0,
        semantics="std_scaled",
        calibration_record={"statistic": "p50", "value": 0.8},
    )
    b = canonical_config_hash(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1.25,
        threshold_effective=1.125,
        semantics="std_scaled",
        calibration_record={"statistic": "p50", "value": 0.9},
    )
    assert a != b


def test_config_hash_rejects_non_finite_configured() -> None:
    with pytest.raises(ValueError):
        canonical_config_hash(
            backbone="effnet",
            bin_mode="temporal_global",
            threshold_configured=float("nan"),
            threshold_effective=float("nan"),
            semantics="direct_l2",
        )


def test_config_inputs_fixed_field_order() -> None:
    """The pre-hash inputs follow the documented seg_config field ordering."""
    inputs = canonical_config_inputs(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=1.25,
        threshold_effective=1.25,
        semantics="direct_l2",
    )
    ordered = [
        "backbone=effnet",
        "bin_mode=temporal_global",
        "threshold_configured=1.25",
        "threshold_effective=1.25",
        "semantics=direct_l2",
        "calibration_record=none",
        "outlier_window=3",
        "strategy_version=1",
        "alias_of_config_id=none",
    ]
    assert inputs == "|".join(ordered)


def test_config_hash_resolution_helper_shape() -> None:
    """A resolved direct_l2 ThresholdResolution round-trips through the canonical form."""
    res = resolve_threshold(1.25)
    assert isinstance(res, ThresholdResolution)
    assert canonical_threshold_of(res) == canonical_threshold(res.configured, res.effective, res.semantics)
