"""Unit tests for global-pool embedding orchestration."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import numpy as np
import pytest

_time_helper_module: Any = ModuleType("nomarr.helpers.time_helper")
_time_helper_module.internal_ms = lambda: 0
_helpers_module: Any = sys.modules.setdefault("nomarr.helpers", ModuleType("nomarr.helpers"))
_helpers_module.time_helper = _time_helper_module
sys.modules.setdefault("nomarr.helpers.time_helper", _time_helper_module)

_GP_EMBED_PATH = Path(__file__).resolve().parents[1] / "strategy_global_pool" / "_embed.py"
_GP_EMBED_SPEC = importlib.util.spec_from_file_location("test_strategy_global_pool_embed", _GP_EMBED_PATH)
assert _GP_EMBED_SPEC is not None and _GP_EMBED_SPEC.loader is not None

gp_embed_mod = importlib.util.module_from_spec(_GP_EMBED_SPEC)
_GP_EMBED_SPEC.loader.exec_module(gp_embed_mod)


@pytest.fixture
def tmp_path(request):
    """Create a unique temp directory path without relying on pytest numbered dirs."""
    safe_name = request.node.name[:20]
    return Path(tempfile.mkdtemp(prefix=f"{safe_name}-{uuid4().hex[:8]}-"))


def _make_alive_it_stub() -> Any:
    """Return an alive_it-compatible stub with text()."""

    class _ProgressBar(list):
        def text(self, _msg: str) -> None:
            return None

    class _AliveItStub:
        def __call__(self, iterable=None, **_kwargs):
            return _ProgressBar([] if iterable is None else iterable)

    return _AliveItStub()


@pytest.mark.unit
def test_gp_embed_delegates_to_common_embed(con, monkeypatch, tmp_path):
    """embed() delegates raw sidecar generation before pooling."""
    common_embed = Mock()
    sidecar = tmp_path / "keep.bb.npy"
    sidecar.write_bytes(b"stub")
    save_pooled = Mock()
    strategy = Mock(return_value=np.array([1.0], dtype=np.float32))

    monkeypatch.setattr(gp_embed_mod, "_common_embed", common_embed)
    monkeypatch.setattr(gp_embed_mod, "_list_embedded_configs", Mock(return_value=frozenset()))
    monkeypatch.setattr(gp_embed_mod, "_discover_audio", Mock(return_value=[tmp_path / "keep.mp3"]))
    monkeypatch.setattr(gp_embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(gp_embed_mod, "_BACKBONES", {"bb": {}})
    monkeypatch.setattr(gp_embed_mod, "_patches_path", lambda _sid, _backbone: sidecar)
    monkeypatch.setattr(gp_embed_mod, "_STRATEGIES", {"mean": strategy})
    monkeypatch.setattr(gp_embed_mod, "_save_pooled", save_pooled)
    monkeypatch.setattr(gp_embed_mod, "_alive_it", _make_alive_it_stub())
    monkeypatch.setattr(gp_embed_mod._np, "load", Mock(return_value=np.array([[1.0, 2.0]], dtype=np.float32)))

    gp_embed_mod.embed(
        con,
        song_ids=frozenset({"keep"}),
        force=True,
        backbones=["bb"],
        device="cuda",
    )

    common_embed.assert_called_once_with(
        con,
        song_ids=frozenset({"keep"}),
        force=True,
        backbones=["bb"],
        device="cuda",
    )


@pytest.mark.unit
def test_gp_embed_skips_missing_sidecar(con, monkeypatch, tmp_path):
    """embed() skips pooling when the raw sidecar is missing."""
    save_pooled = Mock()

    monkeypatch.setattr(gp_embed_mod, "_common_embed", Mock())
    monkeypatch.setattr(gp_embed_mod, "_list_embedded_configs", Mock(return_value=frozenset()))
    monkeypatch.setattr(gp_embed_mod, "_discover_audio", Mock(return_value=[tmp_path / "missing.mp3"]))
    monkeypatch.setattr(gp_embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(gp_embed_mod, "_BACKBONES", {"bb": {}})
    monkeypatch.setattr(gp_embed_mod, "_patches_path", lambda sid, backbone: tmp_path / f"{sid}.{backbone}.npy")
    monkeypatch.setattr(gp_embed_mod, "_STRATEGIES", {"mean": Mock(return_value=np.array([1.0], dtype=np.float32))})
    monkeypatch.setattr(gp_embed_mod, "_save_pooled", save_pooled)
    monkeypatch.setattr(gp_embed_mod, "_alive_it", _make_alive_it_stub())

    gp_embed_mod.embed(con, backbones=["bb"])

    save_pooled.assert_not_called()


@pytest.mark.unit
def test_gp_embed_pools_when_sidecar_exists_and_config_not_done(con, monkeypatch, tmp_path):
    """embed() pools and saves vectors when the sidecar exists and config is new."""
    sidecar = tmp_path / "song.bb.npy"
    sidecar.write_bytes(b"stub")
    strategy = Mock(return_value=np.array([1.0, 2.0], dtype=np.float64))
    save_pooled = Mock()

    monkeypatch.setattr(gp_embed_mod, "_common_embed", Mock())
    monkeypatch.setattr(gp_embed_mod, "_list_embedded_configs", Mock(return_value=frozenset()))
    monkeypatch.setattr(gp_embed_mod, "_discover_audio", Mock(return_value=[tmp_path / "song.mp3"]))
    monkeypatch.setattr(gp_embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(gp_embed_mod, "_BACKBONES", {"bb": {}})
    monkeypatch.setattr(gp_embed_mod, "_patches_path", lambda _sid, _backbone: sidecar)
    monkeypatch.setattr(gp_embed_mod, "_STRATEGIES", {"mean": strategy})
    monkeypatch.setattr(gp_embed_mod, "_save_pooled", save_pooled)
    monkeypatch.setattr(gp_embed_mod, "_alive_it", _make_alive_it_stub())
    monkeypatch.setattr(gp_embed_mod._np, "load", Mock(return_value=np.array([[3.0, 4.0]], dtype=np.float32)))

    gp_embed_mod.embed(con, backbones=["bb"])

    strategy.assert_called_once()
    save_pooled.assert_called_once()
    assert save_pooled.call_args.args[:3] == ("song", "bb", "mean")
    np.testing.assert_array_equal(save_pooled.call_args.args[3], np.array([1.0, 2.0], dtype=np.float32))


@pytest.mark.unit
def test_gp_embed_skips_already_done_config_without_force(con, monkeypatch, tmp_path):
    """embed() does not re-save vectors for configs already marked done."""
    sidecar = tmp_path / "song.bb.npy"
    sidecar.write_bytes(b"stub")
    save_pooled = Mock()
    strategy = Mock(return_value=np.array([1.0], dtype=np.float32))

    monkeypatch.setattr(gp_embed_mod, "_common_embed", Mock())
    monkeypatch.setattr(gp_embed_mod, "_list_embedded_configs", Mock(return_value=frozenset({("bb", "mean")})))
    monkeypatch.setattr(gp_embed_mod, "_discover_audio", Mock(return_value=[tmp_path / "song.mp3"]))
    monkeypatch.setattr(gp_embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(gp_embed_mod, "_BACKBONES", {"bb": {}})
    monkeypatch.setattr(gp_embed_mod, "_patches_path", lambda _sid, _backbone: sidecar)
    monkeypatch.setattr(gp_embed_mod, "_STRATEGIES", {"mean": strategy})
    monkeypatch.setattr(gp_embed_mod, "_save_pooled", save_pooled)
    monkeypatch.setattr(gp_embed_mod, "_alive_it", _make_alive_it_stub())
    monkeypatch.setattr(gp_embed_mod._np, "load", Mock(return_value=np.array([[5.0, 6.0]], dtype=np.float32)))

    gp_embed_mod.embed(con, backbones=["bb"])

    strategy.assert_not_called()
    save_pooled.assert_not_called()


@pytest.mark.unit
def test_gp_embed_force_repools_even_when_config_done(con, monkeypatch, tmp_path):
    """embed() re-saves pooled vectors when force=True even if config already exists."""
    sidecar = tmp_path / "song.bb.npy"
    sidecar.write_bytes(b"stub")
    strategy = Mock(return_value=np.array([7.0], dtype=np.float64))
    save_pooled = Mock()

    monkeypatch.setattr(gp_embed_mod, "_common_embed", Mock())
    monkeypatch.setattr(gp_embed_mod, "_list_embedded_configs", Mock(return_value=frozenset({("bb", "mean")})))
    monkeypatch.setattr(gp_embed_mod, "_discover_audio", Mock(return_value=[tmp_path / "song.mp3"]))
    monkeypatch.setattr(gp_embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(gp_embed_mod, "_BACKBONES", {"bb": {}})
    monkeypatch.setattr(gp_embed_mod, "_patches_path", lambda _sid, _backbone: sidecar)
    monkeypatch.setattr(gp_embed_mod, "_STRATEGIES", {"mean": strategy})
    monkeypatch.setattr(gp_embed_mod, "_save_pooled", save_pooled)
    monkeypatch.setattr(gp_embed_mod, "_alive_it", _make_alive_it_stub())
    monkeypatch.setattr(gp_embed_mod._np, "load", Mock(return_value=np.array([[8.0, 9.0]], dtype=np.float32)))

    gp_embed_mod.embed(con, backbones=["bb"], force=True)

    strategy.assert_called_once()
    save_pooled.assert_called_once()
    np.testing.assert_array_equal(save_pooled.call_args.args[3], np.array([7.0], dtype=np.float32))
