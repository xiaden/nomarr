"""Tests for the PTC head inference helpers.

Covers:
* ``_compute_ptc_head_acts_for_bins`` — pure function, no I/O
* ``cache.binned_ptc_heads`` — save/load/is_done mirror of binned_ctp_heads
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research.classify import _compute_ptc_head_acts_for_bins

# ---------------------------------------------------------------------------
# _compute_ptc_head_acts_for_bins
# ---------------------------------------------------------------------------


def test_compute_ptc_head_acts_for_bins_basic() -> None:
    """Each bin uses the correct inclusive patch range."""
    rng = np.random.default_rng(0)
    acts = rng.random((10, 3)).astype(np.float32)

    bin_start = np.array([0, 5], dtype=np.int32)
    bin_end = np.array([3, 9], dtype=np.int32)

    result = _compute_ptc_head_acts_for_bins(acts, bin_start, bin_end)

    assert result.shape == (2, 3)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result[0], acts[0:4].mean(axis=0), rtol=1e-5)
    np.testing.assert_allclose(result[1], acts[5:10].mean(axis=0), rtol=1e-5)


def test_compute_ptc_head_acts_for_bins_single_patch_per_bin() -> None:
    """Bins with exactly one patch return that patch's acts unchanged."""
    acts = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    bin_start = np.array([0, 1, 2], dtype=np.int32)
    bin_end = np.array([0, 1, 2], dtype=np.int32)

    result = _compute_ptc_head_acts_for_bins(acts, bin_start, bin_end)

    np.testing.assert_array_equal(result, acts)


def test_compute_ptc_head_acts_for_bins_invalid_indices_produce_zeros() -> None:
    """Bins with index -1 produce a zero row."""
    acts = np.ones((5, 2), dtype=np.float32)
    bin_start = np.array([-1, 0], dtype=np.int32)
    bin_end = np.array([-1, 4], dtype=np.int32)

    result = _compute_ptc_head_acts_for_bins(acts, bin_start, bin_end)

    np.testing.assert_array_equal(result[0], np.zeros(2, dtype=np.float32))
    np.testing.assert_allclose(result[1], np.ones(2, dtype=np.float32))


def test_compute_ptc_head_acts_for_bins_start_greater_than_end_produces_zeros() -> None:
    """A bin where start > end (corrupt npz) silently produces zeros."""
    acts = np.ones((5, 2), dtype=np.float32)
    bin_start = np.array([4, 0], dtype=np.int32)
    bin_end = np.array([2, 4], dtype=np.int32)  # first bin: start=4, end=2 — invalid

    result = _compute_ptc_head_acts_for_bins(acts, bin_start, bin_end)

    np.testing.assert_array_equal(result[0], np.zeros(2, dtype=np.float32))
    np.testing.assert_allclose(result[1], np.ones(2, dtype=np.float32))


def test_compute_ptc_head_acts_for_bins_output_dtype_is_float32() -> None:
    """Output is always float32 regardless of input dtype."""
    acts = np.ones((4, 2), dtype=np.float64)
    bin_start = np.array([0], dtype=np.int32)
    bin_end = np.array([3], dtype=np.int32)

    result = _compute_ptc_head_acts_for_bins(acts, bin_start, bin_end)

    assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# cache.binned_ptc_heads — save / load / is_done
# ---------------------------------------------------------------------------


@pytest.fixture()
def ptc_heads_cache(tmp_path: Path, monkeypatch):
    """Patch CACHE_BASE on the binned_ptc_heads module and return helpers."""
    from scripts.embedding_research.cache import binned_ptc_heads as _cache

    monkeypatch.setattr(_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")
    return _cache


def test_save_and_load_roundtrip(ptc_heads_cache) -> None:
    """save() then load() returns identical acts and weights."""
    acts = np.array([[0.1, 0.9], [0.6, 0.4]], dtype=np.float32)
    weights = np.array([5, 3], dtype=np.int32)

    ptc_heads_cache.save("effnet", "approachability_2c", "temporal_global", 1.35, "s1", acts, weights)
    result = ptc_heads_cache.load("effnet", "approachability_2c", "temporal_global", 1.35, "s1")

    assert result is not None
    got_acts, got_weights = result
    np.testing.assert_array_equal(got_acts, acts)
    np.testing.assert_array_equal(got_weights, weights)


def test_load_returns_none_when_file_missing(ptc_heads_cache) -> None:
    """load() returns None when the file does not exist."""
    result = ptc_heads_cache.load("effnet", "approachability_2c", "temporal_global", 1.35, "no_such")
    assert result is None


def test_is_done_false_before_save(ptc_heads_cache) -> None:
    """is_done() returns False when no file exists."""
    assert ptc_heads_cache.is_done("effnet", "approachability_2c", "temporal_global", 1.35, "s1") is False


def test_is_done_true_after_save(ptc_heads_cache) -> None:
    """is_done() returns True once the file has been written."""
    acts = np.ones((2, 3), dtype=np.float32)
    weights = np.array([4, 4], dtype=np.int32)
    ptc_heads_cache.save("effnet", "approachability_2c", "temporal_global", 1.35, "s2", acts, weights)

    assert ptc_heads_cache.is_done("effnet", "approachability_2c", "temporal_global", 1.35, "s2") is True


def test_list_done_keys_returns_saved_entry(ptc_heads_cache) -> None:
    """list_done_keys() includes tuples for every saved file."""
    acts = np.ones((2, 3), dtype=np.float32)
    weights = np.array([2, 2], dtype=np.int32)
    ptc_heads_cache.save("effnet", "approachability_2c", "temporal_global", 1.35, "s3", acts, weights)

    keys = ptc_heads_cache.list_done_keys()
    assert ("s3", "effnet", "approachability_2c", "temporal_global", 1.35) in keys


def test_save_noop_for_empty_acts(ptc_heads_cache) -> None:
    """save() skips writing when acts is empty."""
    acts = np.zeros((0, 3), dtype=np.float32)
    weights = np.zeros(0, dtype=np.int32)
    ptc_heads_cache.save("effnet", "approachability_2c", "temporal_global", 1.35, "empty", acts, weights)

    assert ptc_heads_cache.is_done("effnet", "approachability_2c", "temporal_global", 1.35, "empty") is False


def test_different_heads_are_independent_files(ptc_heads_cache) -> None:
    """Each head gets its own file — is_done is independent per head."""
    acts = np.ones((2, 2), dtype=np.float32)
    weights = np.array([3, 3], dtype=np.int32)
    ptc_heads_cache.save("effnet", "head_a", "temporal_global", 1.35, "s4", acts, weights)

    assert ptc_heads_cache.is_done("effnet", "head_a", "temporal_global", 1.35, "s4") is True
    assert ptc_heads_cache.is_done("effnet", "head_b", "temporal_global", 1.35, "s4") is False
