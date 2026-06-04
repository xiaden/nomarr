"""Unit tests for the shared segmentation loop."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

import scripts.embedding_research.common.segment as segment_mod
from scripts.embedding_research.common.segment import _skip_never, segment


def _make_alive_it_stub():
    """Return an alive_it-compatible stub with text()."""

    class _ProgressBar(list):
        def text(self, _msg: str) -> None:
            return None

    class _AliveItStub:
        def __call__(self, iterable=None, **_kwargs):
            return _ProgressBar([] if iterable is None else iterable)

    return _AliveItStub()


def _write_patches(tmp_path: Path) -> tuple[Path, np.ndarray]:
    """Create a small real patches sidecar for segment-loop tests."""
    patches = np.random.rand(4, 8).astype(np.float32)
    sidecar = tmp_path / "patches.npy"
    np.save(str(sidecar), patches)
    return sidecar, patches


def test_skip_never_always_returns_false() -> None:
    """_skip_never() always allows work to proceed."""
    assert _skip_never("x", "y", "z") is False


def test_segment_raises_when_cache_write_fn_missing(con, monkeypatch) -> None:
    """segment() requires a cache writer in extra_cfg."""
    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())

    with pytest.raises(ValueError, match="cache_write_fn"):
        segment(con, lambda *_args: {}, ["mean"])


def test_segment_skips_song_with_missing_sidecar(con, monkeypatch, tmp_path: Path) -> None:
    """Songs without a patch sidecar are skipped before any segmentation work."""
    missing = tmp_path / "missing.npy"
    cache_write_fn = Mock()
    segment_fn = Mock(return_value={"mean": np.array([1.0], dtype=np.float32)})

    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment._db.load_all_songs",
        lambda _con: [{"song_id": "s1"}],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment.patches_path",
        lambda _sid, _backbone: missing,
    )

    segment(
        con,
        segment_fn,
        ["mean"],
        backbones=["bb"],
        extra_cfg={"cache_write_fn": cache_write_fn},
    )

    segment_fn.assert_not_called()
    cache_write_fn.assert_not_called()


def test_segment_calls_segment_fn_and_cache_write_for_each_strategy(con, monkeypatch, tmp_path: Path) -> None:
    """segment() runs each pending strategy and writes each result to cache."""
    sidecar, expected_patches = _write_patches(tmp_path)
    cache_write_fn = Mock()
    segment_fn = Mock(
        side_effect=lambda _patches, _backbone, strategy_name: {strategy_name: np.array([1.0], dtype=np.float32)}
    )
    strategy_names = ["mean", "max"]

    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment._db.load_all_songs",
        lambda _con: [{"song_id": "s1"}],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment.patches_path",
        lambda _sid, _backbone: sidecar,
    )

    segment(
        con,
        segment_fn,
        strategy_names,
        backbones=["bb"],
        extra_cfg={"cache_write_fn": cache_write_fn},
    )

    assert segment_fn.call_count == 2
    for actual_call, strategy_name in zip(segment_fn.call_args_list, strategy_names, strict=False):
        patches_arg, backbone_arg, strategy_arg = actual_call.args
        np.testing.assert_array_equal(patches_arg, expected_patches)
        assert backbone_arg == "bb"
        assert strategy_arg == strategy_name

    assert cache_write_fn.call_count == 2
    for actual_call, strategy_name in zip(cache_write_fn.call_args_list, strategy_names, strict=False):
        sid_arg, backbone_arg, strategy_arg, result_arg = actual_call.args
        assert sid_arg == "s1"
        assert backbone_arg == "bb"
        assert strategy_arg == strategy_name
        np.testing.assert_array_equal(result_arg[strategy_name], np.array([1.0], dtype=np.float32))


def test_segment_skips_already_done_without_force(con, monkeypatch, tmp_path: Path) -> None:
    """skip_check_fn prevents recomputing a finished strategy when force is False."""
    sidecar, _ = _write_patches(tmp_path)
    cache_write_fn = Mock()
    segment_fn = Mock(return_value={"mean": np.array([1.0], dtype=np.float32)})
    skip_check_fn = Mock(return_value=True)

    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment._db.load_all_songs",
        lambda _con: [{"song_id": "s1"}],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment.patches_path",
        lambda _sid, _backbone: sidecar,
    )

    segment(
        con,
        segment_fn,
        ["mean"],
        backbones=["bb"],
        extra_cfg={"cache_write_fn": cache_write_fn, "skip_check_fn": skip_check_fn},
    )

    skip_check_fn.assert_called_once_with("s1", "bb", "mean")
    segment_fn.assert_not_called()
    cache_write_fn.assert_not_called()


def test_segment_force_bypasses_skip_check(con, monkeypatch, tmp_path: Path) -> None:
    """force=True ignores the skip check and still computes the strategy."""
    sidecar, _ = _write_patches(tmp_path)
    cache_write_fn = Mock()
    segment_fn = Mock(return_value={"mean": np.array([1.0], dtype=np.float32)})
    skip_check_fn = Mock(return_value=True)

    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment._db.load_all_songs",
        lambda _con: [{"song_id": "s1"}],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment.patches_path",
        lambda _sid, _backbone: sidecar,
    )

    segment(
        con,
        segment_fn,
        ["mean"],
        force=True,
        backbones=["bb"],
        extra_cfg={"cache_write_fn": cache_write_fn, "skip_check_fn": skip_check_fn},
    )

    skip_check_fn.assert_not_called()
    segment_fn.assert_called_once()
    cache_write_fn.assert_called_once()


def test_segment_swallows_per_strategy_errors(con, monkeypatch, tmp_path: Path) -> None:
    """A failing strategy does not abort later strategies for the same song."""
    sidecar, _ = _write_patches(tmp_path)
    cache_write_fn = Mock()

    def _segment_fn(_patches: np.ndarray, _backbone: str, strategy_name: str) -> dict[str, np.ndarray]:
        if strategy_name == "broken":
            raise RuntimeError("boom")
        return {strategy_name: np.array([2.0], dtype=np.float32)}

    monkeypatch.setattr(segment_mod, "alive_it", _make_alive_it_stub())
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment._db.load_all_songs",
        lambda _con: [{"song_id": "s1"}],
    )
    monkeypatch.setattr(
        "scripts.embedding_research.common.segment.patches_path",
        lambda _sid, _backbone: sidecar,
    )

    segment(
        con,
        _segment_fn,
        ["broken", "mean"],
        backbones=["bb"],
        extra_cfg={"cache_write_fn": cache_write_fn},
    )

    cache_write_fn.assert_called_once()
    sid_arg, backbone_arg, strategy_arg, result_arg = cache_write_fn.call_args.args
    assert sid_arg == "s1"
    assert backbone_arg == "bb"
    assert strategy_arg == "mean"
    np.testing.assert_array_equal(result_arg["mean"], np.array([2.0], dtype=np.float32))
