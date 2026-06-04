from __future__ import annotations

import numpy as np

from scripts.embedding_research.cache import sim_pairs


def test_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)
    raw_sim = np.random.default_rng(0).random((3, 5), dtype=np.float32)

    sim_pairs.store_sim_pair("effnet", "binned_mean", "song-a", "song-b", raw_sim)
    loaded = sim_pairs.load_sim_pair("effnet", "binned_mean", "song-a", "song-b")

    assert loaded is not None
    assert loaded.shape == raw_sim.shape
    np.testing.assert_array_equal(loaded, raw_sim)


def test_key_ordering(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)
    raw_sim = np.arange(6, dtype=np.float32).reshape(2, 3)

    sim_pairs.store_sim_pair("musicnn", "binned_medoid", "z", "a", raw_sim)
    loaded = sim_pairs.load_sim_pair("musicnn", "binned_medoid", "a", "z")

    assert loaded is not None
    np.testing.assert_array_equal(loaded, raw_sim)


def test_cache_miss_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)

    loaded = sim_pairs.load_sim_pair("effnet", "binned_mean", "missing-a", "missing-b")

    assert loaded is None


def test_shape_reconstruction(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)
    raw_sim = np.ones((1, 7), dtype=np.float32)

    sim_pairs.store_sim_pair("effnet", "binned_max", "shape-a", "shape-b", raw_sim)
    loaded = sim_pairs.load_sim_pair("effnet", "binned_max", "shape-a", "shape-b")

    assert loaded is not None
    assert loaded.shape == (1, 7)
    np.testing.assert_array_equal(loaded, raw_sim)


def test_sim_pair_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)

    assert not sim_pairs.sim_pair_exists("effnet", "binned_mean", "exists-a", "exists-b")

    raw_sim = np.arange(4, dtype=np.float32).reshape(2, 2)
    sim_pairs.store_sim_pair("effnet", "binned_mean", "exists-a", "exists-b", raw_sim)

    assert sim_pairs.sim_pair_exists("effnet", "binned_mean", "exists-a", "exists-b")


def test_store_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sim_pairs, "OUTPUT_ROOT", tmp_path)
    first_raw_sim = np.arange(6, dtype=np.float32).reshape(2, 3)
    second_raw_sim = np.full((2, 3), 99, dtype=np.float32)

    sim_pairs.store_sim_pair("effnet", "binned_mean", "same-a", "same-b", first_raw_sim)
    sim_pairs.store_sim_pair("effnet", "binned_mean", "same-a", "same-b", second_raw_sim)
    loaded = sim_pairs.load_sim_pair("effnet", "binned_mean", "same-a", "same-b")

    assert loaded is not None
    np.testing.assert_array_equal(loaded, first_raw_sim)
