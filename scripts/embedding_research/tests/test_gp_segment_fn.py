"""Unit tests for global-pool segment_fn."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.strategy_global_pool.segment_fn import STRATEGY_NAMES, segment_fn


def test_gp_segment_fn_returns_dict_keyed_by_strategy_name() -> None:
    """segment_fn() returns a one-entry mapping keyed by the requested strategy."""
    strategy_name = STRATEGY_NAMES[0]
    patches = np.random.rand(4, 8).astype(np.float32)

    result = segment_fn(patches, backbone="bb", strategy_name=strategy_name)

    assert set(result) == {strategy_name}
    pooled = result[strategy_name]
    assert pooled.ndim == 1
    assert pooled.shape == (8,)
    assert pooled.dtype == np.float32


def test_gp_segment_fn_raises_for_unknown_strategy_name() -> None:
    """Unknown pooling strategies bubble up as KeyError."""
    patches = np.random.rand(4, 8).astype(np.float32)

    with pytest.raises(KeyError):
        segment_fn(patches, backbone="bb", strategy_name="unknown_strategy")


def test_gp_segment_fn_backbone_arg_is_ignored() -> None:
    """Changing backbone does not affect the pooled result."""
    strategy_name = STRATEGY_NAMES[0]
    patches = np.random.rand(4, 8).astype(np.float32)

    result_a = segment_fn(patches, backbone="a", strategy_name=strategy_name)
    result_b = segment_fn(patches, backbone="b", strategy_name=strategy_name)

    np.testing.assert_allclose(result_a[strategy_name], result_b[strategy_name])
