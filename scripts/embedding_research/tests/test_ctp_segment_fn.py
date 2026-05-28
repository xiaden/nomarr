"""Unit tests for CTP pure helpers and segment closure behavior."""

from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pytest

from scripts.embedding_research.strategy_ctp.segment_fn import (
    STRATEGY_NAMES,
    _decode_strategy_name,
    _empty_result,
    _l2_normalise_vec,
    _run_head_session,
    make_segment_fn,
)


def test_ctp_decode_strategy_name_valid() -> None:
    """A known CTP strategy name decodes to its original parts."""
    strategy_name = STRATEGY_NAMES[0]

    head_name, bin_mode, std_thresh = _decode_strategy_name(strategy_name)

    assert f"ctp_{head_name}_{bin_mode}_{std_thresh:.2f}" == strategy_name


def test_ctp_decode_strategy_name_rejects_wrong_prefix() -> None:
    """Non-CTP prefixes are rejected."""
    with pytest.raises(ValueError, match="Unsupported CTP strategy name"):
        _decode_strategy_name("ptc_something")


def test_ctp_decode_strategy_name_rejects_malformed() -> None:
    """Malformed strategy names fail validation."""
    with pytest.raises(ValueError):
        _decode_strategy_name("ctp_")


def test_ctp_l2_normalise_vec_normalizes_to_unit_length() -> None:
    """Non-zero vectors are normalized and returned as float32."""
    vec = np.array([3.0, 4.0], dtype=np.float32)

    result = _l2_normalise_vec(vec)

    assert result.dtype == np.float32
    assert np.linalg.norm(result) == pytest.approx(1.0)


def test_ctp_l2_normalise_vec_handles_zero_vector() -> None:
    """Zero vectors remain zero and do not error."""
    vec = np.zeros(4, dtype=np.float32)

    result = _l2_normalise_vec(vec)

    assert result.dtype == np.float32
    np.testing.assert_array_equal(result, np.zeros(4, dtype=np.float32))


def test_ctp_run_head_session_calls_session_run() -> None:
    """Head-session inference delegates to session.run with float32 embeddings."""
    session = Mock()
    session.run.return_value = [np.ones((2, 3), dtype=np.float32)]
    embed_batch = np.arange(8, dtype=np.float64).reshape(2, 4)

    result = _run_head_session(session, embed_batch)

    assert result.shape == (2, 3)
    assert result.dtype == np.float32
    args, kwargs = session.run.call_args
    assert args[0] == ["activations"]
    np.testing.assert_array_equal(args[1]["embeddings"], embed_batch.astype(np.float32))
    assert kwargs == {}


def test_ctp_empty_result_has_expected_keys() -> None:
    """The empty-result payload contains the fixed metadata fields."""
    result = _empty_result()

    assert set(result) == {
        "bins",
        "weights",
        "outlier_counts",
        "bin_start_idx",
        "bin_end_idx",
        "pool_names",
    }
    assert all(value.size == 0 for value in result.values())


def test_ctp_segment_fn_empty_patches_returns_empty_result() -> None:
    """The generated segment_fn short-circuits empty inputs."""
    segment_fn = make_segment_fn({}, lambda fn, x: fn(x))
    strategy_name = STRATEGY_NAMES[0]

    result = segment_fn(np.empty((0, 8), dtype=np.float32), "bb", strategy_name)
    expected = _empty_result()

    assert set(result) == set(expected)
    for key in expected:
        np.testing.assert_array_equal(result[key], expected[key])


def test_ctp_segment_fn_missing_head_session_raises() -> None:
    """A valid strategy requires a corresponding configured head session."""
    segment_fn = make_segment_fn({}, lambda fn, x: fn(x))
    strategy_name = STRATEGY_NAMES[0]
    patches = np.ones((2, 8), dtype=np.float32)

    with pytest.raises(KeyError, match="Missing CTP head session"):
        segment_fn(patches, "bb", strategy_name)


def test_ctp_segment_fn_bad_activation_shape_raises() -> None:
    """Activations with fewer than 2 classes raise ValueError."""
    strategy_name = STRATEGY_NAMES[0]
    head_name, _bin_mode, _thresh = _decode_strategy_name(strategy_name)

    session = Mock()
    segment_fn = make_segment_fn(
        {head_name: session},
        lambda _fn, x: np.ones((x.shape[0], 1), dtype=np.float32),
    )
    patches = np.ones((4, 8), dtype=np.float32)

    with pytest.raises(ValueError, match="invalid shape"):
        segment_fn(patches, "bb", strategy_name)


def test_ctp_segment_fn_returns_populated_result_for_valid_activations() -> None:
    """Valid activations produce a populated result dict."""
    strategy_name = STRATEGY_NAMES[0]
    head_name, _bin_mode, _std_thresh = _decode_strategy_name(strategy_name)

    n_patches, dim = 6, 8
    patches = np.ones((n_patches, dim), dtype=np.float32)
    acts = np.ones((n_patches, 2), dtype=np.float32) * 0.5

    session = Mock()
    segment_fn = make_segment_fn(
        {head_name: session},
        lambda _fn, _x: acts,
    )

    result = segment_fn(patches, "bb", strategy_name)

    assert result["bins"].size >= 1
    assert result["weights"].sum() > 0
    pool_names = result["pool_names"].tolist()
    assert len(pool_names) > 0
    for pool_name in pool_names:
        assert result[f"pool_{pool_name}_vec_raw"].ndim == 2
        assert result[f"pool_{pool_name}_vec_norm"].ndim == 2
