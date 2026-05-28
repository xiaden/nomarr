"""Unit tests for PTC strategy-name decoding."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.helpers.binning import BIN_MODES
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
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
        "scripts.embedding_research.strategy_ptc.segment_fn._load_cached_calibration",
        lambda _con, _backbone: None,
    )
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
        "scripts.embedding_research.strategy_ptc.segment_fn._load_cached_calibration",
        lambda _con, _backbone: {"temporal_global": {"p50": 0.2}},
    )
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
