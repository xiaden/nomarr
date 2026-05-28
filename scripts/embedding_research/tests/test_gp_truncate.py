"""Unit tests for global-pool truncation analysis."""

from __future__ import annotations

import pytest

pytest.skip("Stale test file for removed strategy_global_pool internals.", allow_module_level=True)

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock

import numpy as np
import pytest

_tqdm_module: Any = ModuleType("tqdm")
_tqdm_module.tqdm = lambda iterable=None, **_kwargs: iterable
sys.modules.setdefault("tqdm", _tqdm_module)

_time_helper_module: Any = ModuleType("nomarr.helpers.time_helper")
_time_helper_module.internal_ms = lambda: SimpleNamespace(value=0)
_helpers_module: Any = sys.modules.setdefault("nomarr.helpers", ModuleType("nomarr.helpers"))
_helpers_module.time_helper = _time_helper_module
sys.modules.setdefault("nomarr.helpers.time_helper", _time_helper_module)

_GP_TRUNCATE_PATH = Path(__file__).resolve().parents[1] / "strategy_global_pool" / "_truncate.py"
_GP_TRUNCATE_SPEC = importlib.util.spec_from_file_location("test_strategy_global_pool_truncate", _GP_TRUNCATE_PATH)
assert _GP_TRUNCATE_SPEC is not None and _GP_TRUNCATE_SPEC.loader is not None

gp_truncate_mod = importlib.util.module_from_spec(_GP_TRUNCATE_SPEC)
_GP_TRUNCATE_SPEC.loader.exec_module(gp_truncate_mod)


@pytest.mark.unit
def test_flat_rep_normalizes_mean_vector():
    """_flat_rep() mean-pools patches and L2-normalizes the result."""
    patches = np.array(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )

    result = gp_truncate_mod._flat_rep(patches)
    expected = np.array([1.0, 1.0], dtype=np.float32)
    expected = expected / np.linalg.norm(expected)

    assert result is not None
    np.testing.assert_allclose(result, expected.astype(np.float32), rtol=1e-5)


@pytest.mark.unit
def test_flat_rep_returns_none_for_zero_norm_mean():
    """_flat_rep() returns None when the pooled vector norm is effectively zero."""
    patches = np.zeros((4, 2), dtype=np.float32)

    assert gp_truncate_mod._flat_rep(patches) is None


@pytest.mark.unit
def test_binned_rep_normalizes_segment_means():
    """_binned_rep() averages normalized bin representatives and renormalizes them."""
    patches = np.array(
        [
            [1.0, 0.0],
            [1.0, 0.0],
            [0.0, 1.0],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )

    result = gp_truncate_mod._binned_rep(patches, "temporal_global", 0.3)
    expected = np.array([1.0, 1.0], dtype=np.float32)
    expected = expected / np.linalg.norm(expected)

    assert result is not None
    np.testing.assert_allclose(result, expected.astype(np.float32), rtol=1e-5)


@pytest.mark.unit
def test_binned_rep_returns_none_when_no_nonzero_bin_rep_survives():
    """_binned_rep() returns None when every candidate bin collapses to zero."""
    patches = np.zeros((4, 2), dtype=np.float32)

    assert gp_truncate_mod._binned_rep(patches, "temporal_global", 0.3) is None


@pytest.mark.unit
def test_cosine_returns_dot_product_for_unit_vectors():
    """_cosine() is just the dot product for already normalized vectors."""
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.6, 0.8], dtype=np.float32)

    assert gp_truncate_mod._cosine(a, b) == pytest.approx(0.6)


@pytest.mark.unit
def test_analyze_truncation_without_valid_patch_files_is_noop(con, monkeypatch, tmp_path):
    """analyze_truncation() skips writes when no candidate song has a readable patch file."""
    upsert = Mock()
    load_patches = Mock(side_effect=AssertionError("np.load should not be called for missing files"))

    monkeypatch.setattr(gp_truncate_mod, "upsert_truncation_robustness", upsert)
    monkeypatch.setattr(gp_truncate_mod, "patches_path", lambda sid, backbone: tmp_path / backbone / f"{sid}.npy")
    monkeypatch.setattr(gp_truncate_mod.np, "load", load_patches)

    gp_truncate_mod.analyze_truncation(con, backbones=["bb"], song_ids=frozenset({"missing-song"}))

    upsert.assert_not_called()
    load_patches.assert_not_called()


@pytest.mark.unit
def test_analyze_truncation_upserts_expected_mean_similarities(con, monkeypatch, tmp_path):
    """analyze_truncation() computes flat and binned means and persists their delta."""
    upsert = Mock()
    patch_file = tmp_path / "bb" / "song-1.npy"
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_bytes(b"stub")
    patches = np.tile(np.array([[1.0, 0.0]], dtype=np.float32), (8, 1))

    monkeypatch.setattr(gp_truncate_mod, "upsert_truncation_robustness", upsert)
    monkeypatch.setattr(gp_truncate_mod, "patches_path", lambda _sid, _backbone: patch_file)
    monkeypatch.setattr(gp_truncate_mod.np, "load", Mock(return_value=patches))
    monkeypatch.setattr(gp_truncate_mod, "BIN_MODES", ["temporal_global"], raising=False)
    monkeypatch.setattr(gp_truncate_mod, "DIST_THRESHOLDS", [0.3], raising=False)

    gp_truncate_mod.analyze_truncation(
        con,
        backbones=["bb"],
        song_ids=frozenset({"song-1"}),
        thresholds_by_backbone_mode={("bb", "temporal_global"): [0.3]},
    )

    upsert.assert_called_once()
    args = upsert.call_args.args
    assert args[:4] == (con, "bb", "temporal_global", 0.3)
    np.testing.assert_allclose(args[4:], (1.0, 1.0, 0.0), rtol=1e-5)
