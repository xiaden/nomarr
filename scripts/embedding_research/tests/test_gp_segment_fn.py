"""Unit tests for global-pool segment_fn."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.cache import flat_vecs
from scripts.embedding_research.pooling import pool_medoid
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


# ---------------------------------------------------------------------------
# Flat medoid identity and EffNet/MusicNN backbone separation
# ---------------------------------------------------------------------------


def test_medoid_is_a_global_pool_strategy() -> None:
    """medoid is registered and selectable as a flat global-pool strategy."""
    assert "medoid" in STRATEGY_NAMES


def test_gp_segment_fn_medoid_returns_observed_patch() -> None:
    """segment_fn(..., 'medoid') returns one of the input patch rows exactly."""
    patches = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.8, 0.6, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    result = segment_fn(patches, backbone="effnet", strategy_name="medoid")
    pooled = result["medoid"]
    assert pooled.dtype == np.float32
    assert any(np.array_equal(pooled, row) for row in patches)


def test_global_pool_medoid_identity_is_backbone_scoped() -> None:
    """EffNet and MusicNN each get their own independently keyed medoid."""
    effnet = "global_pool:effnet:medoid"
    musicnn = "global_pool:musicnn:medoid"
    assert effnet != musicnn
    assert effnet.startswith("global_pool:effnet:")
    assert musicnn.startswith("global_pool:musicnn:")


def test_medoid_cache_identity_is_backbone_scoped(tmp_path, monkeypatch) -> None:
    """Cache path stays {backbone}/{strategy}/flat/{sid}.npy for each backbone."""
    monkeypatch.setattr(flat_vecs, "_CACHE_ROOT", tmp_path / "cache")
    effnet = flat_vecs._vec_path("s1", "effnet", "medoid")
    musicnn = flat_vecs._vec_path("s1", "musicnn", "medoid")
    assert effnet != musicnn
    assert effnet.parents[2].name == "effnet"
    assert musicnn.parents[2].name == "musicnn"
    assert effnet.parents[1].name == "medoid"
    assert effnet.parents[0].name == "flat"
    assert effnet.name == "s1.npy"


def test_pool_medoid_never_mixes_backbones() -> None:
    """Each backbone's medoid is computed from its own patches only."""
    effnet = np.array([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0]], dtype=np.float32)
    musicnn = np.array([[0.0, 1.0, 0.0], [0.0, 0.9, 0.1]], dtype=np.float32)

    e_medoid = pool_medoid(effnet)
    m_medoid = pool_medoid(musicnn)

    assert any(np.array_equal(e_medoid, row) for row in effnet)
    assert any(np.array_equal(m_medoid, row) for row in musicnn)


def test_configured_flat_strategies_preserved_when_medoid_present() -> None:
    """An explicit strategy config keeps every requested strategy, medoid included.

    segment_fn produces a correct, independently keyed result for each configured
    flat strategy — configuring medoid does not drop mean/median/max_norm.
    """
    patches = np.random.rand(5, 8).astype(np.float32)
    for strategy_name in ("mean", "median", "max_norm", "medoid"):
        result = segment_fn(patches, backbone="bb", strategy_name=strategy_name)
        assert set(result) == {strategy_name}
        pooled = result[strategy_name]
        assert pooled.ndim == 1
        assert pooled.shape == (8,)
        assert pooled.dtype == np.float32


def test_medoid_cache_write_load_roundtrip_is_backbone_scoped(tmp_path, monkeypatch) -> None:
    """EffNet and MusicNN medoids write/load to distinct cache paths and survive a roundtrip.

    Each backbone's medoid is saved under its own {backbone}/medoid/flat path and
    loaded back as the identical observed patch — proving the independent keyed
    identity is honoured end-to-end through cache/flat_vecs.py.
    """
    monkeypatch.setattr(flat_vecs, "_CACHE_ROOT", tmp_path / "cache")

    eff_patches = np.array([[1.0, 0.0, 0.0], [0.8, 0.6, 0.0]], dtype=np.float32)
    mus_patches = np.array([[0.0, 1.0, 0.0], [0.0, 0.8, 0.6]], dtype=np.float32)

    e = segment_fn(eff_patches, backbone="effnet", strategy_name="medoid")["medoid"]
    m = segment_fn(mus_patches, backbone="musicnn", strategy_name="medoid")["medoid"]

    flat_vecs.save_pooled("s1", "effnet", "medoid", e)
    flat_vecs.save_pooled("s1", "musicnn", "medoid", m)

    loaded_e = flat_vecs.load_pooled("s1", "effnet", "medoid")
    loaded_m = flat_vecs.load_pooled("s1", "musicnn", "medoid")

    np.testing.assert_array_equal(loaded_e, e)
    np.testing.assert_array_equal(loaded_m, m)
    assert any(np.array_equal(e, row) for row in eff_patches)
    assert any(np.array_equal(m, row) for row in mus_patches)
    assert flat_vecs._vec_path("s1", "effnet", "medoid") != flat_vecs._vec_path("s1", "musicnn", "medoid")
