"""Unit tests for PTC strategy-name decoding and the PTC segment adapter.

Two-track structure (Phase 3): the NEW-DEFAULT ``direct_l2`` track (the default
``make_segment_fn`` path applies the configured threshold directly,
``effective == configured``) is UNMARKED.  The explicit LEGACY SCALED track —
``semantics="std_scaled"`` with a recorded calibration basis (configured x p50),
and the loud rejection when no basis is supplied — is marked
``@pytest.mark.legacy_scaled`` so the two semantics are never confused.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.binning import BIN_MODES
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.helpers.thresholds import STD_SCALED
from scripts.embedding_research.strategy_ptc.segment_fn import STRATEGY_NAMES, _decode_strategy_name, make_segment_fn


@pytest.mark.parametrize("bin_mode", BIN_MODES)
def test_ptc_decode_strategy_name_valid(bin_mode: str) -> None:
    """Each configured bin mode decodes from a valid PTC strategy name."""
    assert _decode_strategy_name(f"ptc_{bin_mode}_1.00") == (bin_mode, 1.0)


def test_ptc_decode_strategy_name_rejects_wrong_prefix() -> None:
    """Non-PTC prefixes are rejected."""
    with pytest.raises(ValueError, match="Unsupported PTC strategy name"):
        _decode_strategy_name("gp_something")


def test_ptc_decode_strategy_name_rejects_unknown_bin_mode() -> None:
    """Unknown bin modes are rejected."""
    with pytest.raises(ValueError, match="Unknown PTC bin mode"):
        _decode_strategy_name("ptc_badmode_1.0")


def test_ptc_decode_strategy_name_rejects_malformed() -> None:
    """Malformed strategy names fail validation."""
    with pytest.raises(ValueError):
        _decode_strategy_name("ptc_")


def test_ptc_strategy_names_shape() -> None:
    """STRATEGY_NAMES has one entry per (bin_mode, std_thresh) combination."""
    expected_count = len(BIN_MODES) * len(STD_THRESHOLDS)

    assert len(STRATEGY_NAMES) == expected_count
    assert STRATEGY_NAMES[0] == f"ptc_{BIN_MODES[0]}_{STD_THRESHOLDS[0]:.2f}"
    assert all(name.startswith("ptc_") for name in STRATEGY_NAMES)


def test_ptc_make_segment_fn_empty_segments_returns_empty_result(monkeypatch) -> None:
    """When temporal_segment yields no segments, the closure returns empty arrays."""
    monkeypatch.setattr(
        "scripts.embedding_research.strategy_ptc.segment_fn.temporal_segment",
        lambda *_args, **_kwargs: [],
    )

    fn = make_segment_fn(None)
    patches = np.ones((4, 8), dtype=np.float32)

    result = fn(patches, "bb", STRATEGY_NAMES[0])

    assert result["bins"].size == 0
    assert result["weights"].size == 0
    assert result["outlier_counts"].size == 0


def test_ptc_make_segment_fn_normal_segments_returns_populated_result(monkeypatch) -> None:
    """When temporal_segment returns segments, the closure produces a populated result dict."""
    dim = 8

    def _mock_pool_segment(_raw, _unit, indices):
        return {
            "mean": {
                "vec_raw": np.ones(dim, dtype=np.float32),
                "vec_norm": (np.ones(dim, dtype=np.float32) / np.sqrt(dim)).astype(np.float32),
                "selected_global_idx": indices[0],
                "selected_local_idx": 0,
                "medoid_centrality": 0.9,
            }
        }

    monkeypatch.setattr(
        "scripts.embedding_research.strategy_ptc.segment_fn.temporal_segment",
        lambda *_args, **_kwargs: [
            {"indices": [0, 1], "outlier_count": 0},
            {"indices": [2, 3], "outlier_count": 1},
        ],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.strategy_ptc.segment_fn._pool_segment",
        _mock_pool_segment,
    )

    fn = make_segment_fn(None)
    patches = np.ones((4, dim), dtype=np.float32)

    result = fn(patches, "bb", STRATEGY_NAMES[0])

    assert result["bins"].tolist() == [0, 1]
    assert result["weights"].tolist() == [2, 2]
    assert "pool_names" in result
    assert result["pool_mean_vec_raw"].shape == (2, dim)
    assert result["pool_mean_vec_norm"].shape == (2, dim)


def _threshold_spy(monkeypatch):
    """Monkeypatch temporal_segment to capture the effective threshold it receives."""
    captured: dict[str, object] = {}

    def _spy(*args, **_kwargs):
        captured["threshold"] = args[1]
        return []

    monkeypatch.setattr(
        "scripts.embedding_research.strategy_ptc.segment_fn.temporal_segment",
        _spy,
    )
    return captured


def test_ptc_default_semantics_is_direct_l2_uses_configured_threshold(monkeypatch) -> None:
    """The default PTC path applies the configured threshold directly (effective == configured).

    Segment boundaries follow direct unit-vector L2 on unit vectors: no p50
    multiplier and no 0.1 fallback.  The threshold handed to temporal_segment must
    equal the configured value decoded from the strategy name.
    """
    captured = _threshold_spy(monkeypatch)
    fn = make_segment_fn(None)
    _bin_mode, configured = _decode_strategy_name(STRATEGY_NAMES[0])

    fn(np.ones((4, 8), dtype=np.float32), "bb", STRATEGY_NAMES[0])

    assert captured["threshold"] == configured


@pytest.mark.legacy_scaled
def test_ptc_std_scaled_uses_explicit_calibration_basis(monkeypatch) -> None:
    """The explicit std_scaled track scales by the provided calibration basis.

    Legacy scaled semantics (configured x p50 basis): effective == configured x
    p50 basis; the calibration basis must be supplied explicitly (no implicit
    0.1 fallback).
    """
    captured = _threshold_spy(monkeypatch)
    bin_mode, configured = _decode_strategy_name(STRATEGY_NAMES[0])
    basis = 0.8
    fn = make_segment_fn(
        None,
        semantics=STD_SCALED,
        calibration_records={bin_mode: {"statistic": "p50", "value": basis}},
    )

    fn(np.ones((4, 8), dtype=np.float32), "bb", STRATEGY_NAMES[0])

    assert captured["threshold"] == pytest.approx(configured * basis)


@pytest.mark.legacy_scaled
def test_ptc_std_scaled_without_explicit_basis_raises(monkeypatch) -> None:
    """std_scaled without a usable explicit basis for the bin_mode is rejected loudly."""
    _threshold_spy(monkeypatch)
    _bin_mode, _configured = _decode_strategy_name(STRATEGY_NAMES[0])
    fn = make_segment_fn(None, semantics=STD_SCALED, calibration_records={})

    with pytest.raises(ValueError, match="std_scaled PTC segmentation requires an explicit calibration basis"):
        fn(np.ones((4, 8), dtype=np.float32), "bb", STRATEGY_NAMES[0])


def test_ptc_make_segment_fn_default_semantics_is_direct_l2(monkeypatch) -> None:
    """make_segment_fn defaults to direct_l2 (the adapter never defaults to std_scaled)."""
    captured = _threshold_spy(monkeypatch)
    fn = make_segment_fn(None)

    fn(np.ones((4, 8), dtype=np.float32), "bb", STRATEGY_NAMES[0])

    # Direct-l2 default: effective == configured even when no calibration basis
    # is supplied anywhere.
    _configured_from_name = _decode_strategy_name(STRATEGY_NAMES[0])[1]
    assert captured["threshold"] == _configured_from_name
