"""Unit tests for CTP pure helpers and segment closure behavior.

LEGACY SCALED track (whole module, ``pytestmark = legacy_scaled``): CTP is
ARCHIVAL and its segmentation threshold is a per-song score_std multiplier
(``strategy_ctp/segment_fn.py``), NOT the new-default ``direct_l2`` semantics.
Every assertion here pins legacy CTP machinery/behavior and claims nothing about
the new-default threshold track.  No CTP behavior is changed; this module is only
labeled so it is never mistaken for a direct-L2 default test.
"""

from __future__ import annotations

from unittest.mock import Mock

import numpy as np
import pytest

from scripts.embedding_research.strategy_ctp.segment_fn import (
    STRATEGY_NAMES,
    _decode_strategy_name,
    _empty_result,
    _run_head_session,
    make_segment_fn,
)

# Whole-file marker: this module pins the ARCHIVAL LEGACY SCALED CTP track.
pytestmark = pytest.mark.legacy_scaled


def test_ctp_decode_strategy_name_valid() -> None:
    """A known CTP strategy name decodes to its original parts."""
    strategy_name = STRATEGY_NAMES[0]

    head_name, std_thresh = _decode_strategy_name(strategy_name)

    assert f"ctp_{head_name}_{std_thresh:.2f}" == strategy_name


def test_ctp_decode_strategy_name_rejects_wrong_prefix() -> None:
    """Non-CTP prefixes are rejected."""
    with pytest.raises(ValueError, match="Unsupported CTP strategy name"):
        _decode_strategy_name("ptc_something")


def test_ctp_decode_strategy_name_rejects_malformed() -> None:
    """Malformed strategy names fail validation."""
    with pytest.raises(ValueError):
        _decode_strategy_name("ctp_")


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
    head_name, _thresh = _decode_strategy_name(strategy_name)

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
    head_name, _std_thresh = _decode_strategy_name(strategy_name)

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
