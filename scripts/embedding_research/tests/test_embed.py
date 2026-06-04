"""Unit tests for shared embedding sidecar generation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
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

from scripts.embedding_research.common import embed as embed_mod


@pytest.fixture
def tmp_path(request):
    """Create a unique temp directory path without relying on pytest numbered dirs."""
    safe_name = request.node.name[:20]
    return Path(tempfile.mkdtemp(prefix=f"{safe_name}-{uuid4().hex[:8]}-"))


def _configure_sidecar_paths(monkeypatch: pytest.MonkeyPatch, tmp_path, sid: str) -> None:
    """Redirect sidecar output into tmp_path for isolation."""
    monkeypatch.setattr(embed_mod, "_PATCHES_DIR", tmp_path)
    monkeypatch.setattr(embed_mod, "_patches_path", lambda _sid, backbone: tmp_path / backbone / f"{_sid}.npy")
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)


@pytest.mark.unit
def test_embed_song_raw_skips_when_sidecar_exists_without_force(con, monkeypatch, tmp_path):
    """Existing sidecar short-circuits work when force is False."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-existing"
    _configure_sidecar_paths(monkeypatch, tmp_path, sid)

    sidecar = tmp_path / "bb" / f"{sid}.npy"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    np.save(sidecar, np.array([[1.0]], dtype=np.float32))

    upsert_song = Mock()
    monkeypatch.setattr(embed_mod, "_upsert_song", upsert_song)

    load_audio_fn = Mock(side_effect=AssertionError("load_audio_fn should not be called"))

    result = embed_mod._embed_song_raw(
        path=song_path,
        backbone_name="bb",
        backbone_cfg={"backbone_name": "bb-model"},
        load_audio_fn=load_audio_fn,
        preprocess_fn=Mock(),
        session=Mock(),
        run_in_batches_fn=Mock(),
        batch_size=4,
        con=con,
        force=False,
    )

    assert result is False
    assert sidecar.exists()
    load_audio_fn.assert_not_called()
    upsert_song.assert_not_called()


@pytest.mark.unit
def test_embed_song_raw_none_patches_returns_false(con, monkeypatch, tmp_path):
    """None patches are treated as no work and do not write a sidecar."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-none"
    _configure_sidecar_paths(monkeypatch, tmp_path, sid)

    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {
            "path": str(path),
            "artist": "Artist",
            "album": "Album",
            "title": "Title",
            "genre": "Genre",
        },
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    waveform = np.array([0.1, -0.1], dtype=np.float32)
    load_audio_fn = Mock(return_value=SimpleNamespace(waveform=waveform))
    preprocess_fn = Mock(return_value=None)
    run_in_batches_fn = Mock(side_effect=AssertionError("run_in_batches_fn should not be called"))

    result = embed_mod._embed_song_raw(
        path=song_path,
        backbone_name="bb",
        backbone_cfg={"backbone_name": "bb-model"},
        load_audio_fn=load_audio_fn,
        preprocess_fn=preprocess_fn,
        session=Mock(),
        run_in_batches_fn=run_in_batches_fn,
        batch_size=4,
        con=con,
        force=False,
    )

    assert result is False
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once()
    run_in_batches_fn.assert_not_called()
    assert not (tmp_path / "bb" / f"{sid}.npy").exists()


@pytest.mark.unit
def test_embed_song_raw_empty_patches_returns_false(con, monkeypatch, tmp_path):
    """Empty patch output skips inference and sidecar writing."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-empty"
    _configure_sidecar_paths(monkeypatch, tmp_path, sid)

    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {
            "path": str(path),
            "artist": "Artist",
            "album": "Album",
            "title": "Title",
            "genre": "Genre",
        },
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    waveform = np.array([0.1, -0.1], dtype=np.float32)
    load_audio_fn = Mock(return_value=SimpleNamespace(waveform=waveform))
    preprocess_fn = Mock(return_value=[])
    run_in_batches_fn = Mock(side_effect=AssertionError("run_in_batches_fn should not be called"))

    result = embed_mod._embed_song_raw(
        path=song_path,
        backbone_name="bb",
        backbone_cfg={"backbone_name": "bb-model"},
        load_audio_fn=load_audio_fn,
        preprocess_fn=preprocess_fn,
        session=Mock(),
        run_in_batches_fn=run_in_batches_fn,
        batch_size=4,
        con=con,
        force=False,
    )

    assert result is False
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once()
    run_in_batches_fn.assert_not_called()
    assert not (tmp_path / "bb" / f"{sid}.npy").exists()


@pytest.mark.unit
def test_embed_song_raw_saves_sidecar_and_returns_true_when_embeddings_created(con, monkeypatch, tmp_path):
    """Successful embedding writes the raw sidecar to disk and reports work done."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-happy"
    _configure_sidecar_paths(monkeypatch, tmp_path, sid)

    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {
            "path": str(path),
            "artist": "Artist",
            "album": "Album",
            "title": "Title",
            "genre": "Genre",
        },
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    waveform = np.array([0.1, -0.1, 0.2], dtype=np.float32)
    patches = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    expected_embeddings = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)

    load_audio_fn = Mock(return_value=SimpleNamespace(waveform=waveform))
    preprocess_fn = Mock(return_value=patches)
    session = Mock()
    session.run.return_value = [expected_embeddings]

    def run_in_batches_fn(predict_fn, batch, batch_size):
        assert batch_size == 2
        np.testing.assert_array_equal(batch, patches)
        return predict_fn(batch)

    result = embed_mod._embed_song_raw(
        path=song_path,
        backbone_name="bb",
        backbone_cfg={"backbone_name": "bb-model"},
        load_audio_fn=load_audio_fn,
        preprocess_fn=preprocess_fn,
        session=session,
        run_in_batches_fn=run_in_batches_fn,
        batch_size=2,
        con=con,
        force=False,
    )

    sidecar = tmp_path / "bb" / f"{sid}.npy"

    assert result is True
    assert sidecar.exists()
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once_with(waveform, "bb-model")
    session.run.assert_called_once()
    np.testing.assert_array_equal(np.load(sidecar), expected_embeddings)


def _install_embed_runtime_stubs() -> dict[str, Mock]:
    """Install stub nomarr modules used by embed() dynamic imports."""
    _onnx_mod: Any = ModuleType("nomarr.components.ml.onnx.ml_session_comp")
    create_session = Mock(return_value=Mock())
    run_in_batches = Mock()
    _onnx_mod.create_session = create_session
    _onnx_mod._BACKBONE_BATCH_SIZE = 4
    _onnx_mod._run_in_batches = run_in_batches

    sys.modules["nomarr.components.ml.onnx.ml_session_comp"] = _onnx_mod
    sys.modules.setdefault("nomarr.components", ModuleType("nomarr.components"))
    sys.modules.setdefault("nomarr.components.ml", ModuleType("nomarr.components.ml"))
    sys.modules.setdefault("nomarr.components.ml.onnx", ModuleType("nomarr.components.ml.onnx"))
    sys.modules.setdefault("nomarr.components.ml.audio", ModuleType("nomarr.components.ml.audio"))

    _audio_comp: Any = ModuleType("nomarr.components.ml.audio.ml_audio_comp")
    _audio_comp.load_audio_mono = Mock()
    sys.modules["nomarr.components.ml.audio.ml_audio_comp"] = _audio_comp

    _preprocess_comp: Any = ModuleType("nomarr.components.ml.audio.ml_preprocess_comp")
    _preprocess_comp.preprocess_for_backbone = Mock()
    sys.modules["nomarr.components.ml.audio.ml_preprocess_comp"] = _preprocess_comp

    return {
        "create_session": create_session,
        "run_in_batches": run_in_batches,
        "load_audio_mono": _audio_comp.load_audio_mono,
        "preprocess_for_backbone": _preprocess_comp.preprocess_for_backbone,
    }


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
def test_embed_no_audio_files_is_noop(con, monkeypatch, tmp_path):
    """embed() skips song work when discovery returns no audio files."""
    runtime_stubs = _install_embed_runtime_stubs()
    patches_dir = tmp_path / "patches"
    embed_song_raw = Mock()

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_PATCHES_DIR", patches_dir)
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[]))
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, backbones=["bb"])

    assert patches_dir.exists()
    runtime_stubs["create_session"].assert_called_once_with("model.onnx", device="cpu", vram_limit_bytes=None)
    embed_song_raw.assert_not_called()


@pytest.mark.unit
def test_embed_filters_by_song_ids(con, monkeypatch, tmp_path):
    """embed() only processes discovered songs whose IDs are in scope."""
    _install_embed_runtime_stubs()
    keep_path = tmp_path / "keep.mp3"
    skip_path = tmp_path / "skip.mp3"
    embed_song_raw = Mock(return_value=True)

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_PATCHES_DIR", tmp_path / "patches")
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[keep_path, skip_path]))
    monkeypatch.setattr(embed_mod, "_song_id", lambda path: Path(path).stem)
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, song_ids=frozenset({"keep"}), backbones=["bb"])

    embed_song_raw.assert_called_once()
    assert embed_song_raw.call_args.args[0] == keep_path


@pytest.mark.unit
def test_embed_counts_done_and_skipped(con, monkeypatch, tmp_path):
    """embed() treats True as done and False as skipped without raising."""
    _install_embed_runtime_stubs()
    first_path = tmp_path / "first.mp3"
    second_path = tmp_path / "second.mp3"
    embed_song_raw = Mock(side_effect=[True, False])

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_PATCHES_DIR", tmp_path / "patches")
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[first_path, second_path]))
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, backbones=["bb"])

    assert embed_song_raw.call_count == 2


@pytest.mark.unit
def test_embed_errors_dont_propagate(con, monkeypatch, tmp_path):
    """embed() swallows per-song errors and keeps orchestrating."""
    _install_embed_runtime_stubs()
    song_path = tmp_path / "broken.mp3"
    embed_song_raw = Mock(side_effect=RuntimeError("boom"))

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_PATCHES_DIR", tmp_path / "patches")
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[song_path]))
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, backbones=["bb"])

    embed_song_raw.assert_called_once()
