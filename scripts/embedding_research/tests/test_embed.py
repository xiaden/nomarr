"""Unit tests for shared embedding sidecar generation (durable publication contract).

Phase 2 rewired ``_embed_song_raw`` to publish through the frozen StreamStore (staged
fsync/rename durable write + transactional ``pending`` registration) instead of a bare
``np.save``.  Skip semantics are registry-driven: a song/backbone is skipped only when a
verified ``ready`` registry row already exists (not merely because a sidecar file exists),
and ``force=True`` recomputes + publishes an immutable replacement.
"""

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
from scripts.embedding_research.streams import StreamStore


@pytest.fixture
def tmp_path(request):
    """Create a unique temp directory path without relying on pytest numbered dirs."""
    safe_name = request.node.name[:20]
    return Path(tempfile.mkdtemp(prefix=f"{safe_name}-{uuid4().hex[:8]}-"))


def _store(con, tmp_path) -> StreamStore:
    """An isolated StreamStore whose artifacts land under tmp_path."""
    return StreamStore(con, output_root=tmp_path)


@pytest.mark.unit
def test_embed_song_raw_skips_when_ready_registry_row_exists_without_force(con, monkeypatch, tmp_path):
    """A verified ready registry row short-circuits work when force is False."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-existing"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)

    store = _store(con, tmp_path)
    store.publish(sid, "bb", np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32), run_id="r1")
    store.reconcile()
    assert store.has_ready(sid, "bb")

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
        store=store,
        run_id="r2",
        force=False,
    )

    assert result is False
    load_audio_fn.assert_not_called()
    upsert_song.assert_not_called()


@pytest.mark.unit
def test_embed_song_raw_none_patches_returns_false(con, monkeypatch, tmp_path):
    """None patches are treated as no work and do not publish a stream."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-none"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)
    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {"path": str(path), "artist": "Artist", "album": "Album", "title": "Title", "genre": "Genre"},
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    store = _store(con, tmp_path)
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
        store=store,
        run_id="r",
        force=False,
    )

    assert result is False
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once()
    run_in_batches_fn.assert_not_called()
    # Nothing was published: no ready registry row and no digest artifact under streams/.
    assert not store.has_ready(sid, "bb")
    assert list((tmp_path / "streams").glob("*.npy")) == []


@pytest.mark.unit
def test_embed_song_raw_empty_patches_returns_false(con, monkeypatch, tmp_path):
    """Empty patch output skips inference and publication."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-empty"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)
    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {"path": str(path), "artist": "Artist", "album": "Album", "title": "Title", "genre": "Genre"},
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    store = _store(con, tmp_path)
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
        store=store,
        run_id="r",
        force=False,
    )

    assert result is False
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once()
    run_in_batches_fn.assert_not_called()
    # Nothing was published: no ready registry row and no digest artifact under streams/.
    assert not store.has_ready(sid, "bb")
    assert list((tmp_path / "streams").glob("*.npy")) == []


@pytest.mark.unit
def test_embed_song_raw_publishes_sidecar_and_returns_true(con, monkeypatch, tmp_path):
    """Successful embedding durably publishes the raw sidecar and reports work done."""
    song_path = tmp_path / "artist - title.mp3"
    song_path.write_bytes(b"")
    sid = "song-happy"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)
    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {"path": str(path), "artist": "Artist", "album": "Album", "title": "Title", "genre": "Genre"},
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_args, **_kwargs: None)

    store = _store(con, tmp_path)
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
        store=store,
        run_id="r1",
        force=False,
    )

    assert result is True
    load_audio_fn.assert_called_once_with(str(song_path), target_sr=16000)
    preprocess_fn.assert_called_once_with(waveform, "bb-model")
    session.run.assert_called_once()
    # Immutable publication: reconcile promotes the pending row to ready; the ready
    # artifact is ONE digest-named .npy under streams/ that round-trips to the output.
    store.reconcile()
    assert store.has_ready(sid, "bb")
    got = store.batch_gather(sid, "bb", list(range(patches.shape[0])))
    np.testing.assert_array_equal(got, expected_embeddings)
    digest_npys = list((tmp_path / "streams").glob(f"{sid}.bb.*.npy"))
    assert len(digest_npys) == 1
    # A successful publish leaves no .tmp staging leftover.
    staging = tmp_path / "streams" / ".staging"
    assert not staging.exists() or not list(staging.glob("*.tmp"))


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
    embed_song_raw = Mock()

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[]))
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, backbones=["bb"])

    runtime_stubs["create_session"].assert_called_once_with("model.onnx", device="cpu", vram_limit_bytes=None)
    embed_song_raw.assert_not_called()
    # No audio files means nothing was published: the registry holds no ready stream.
    assert _store(con, tmp_path).ready_rows() == []


@pytest.mark.unit
def test_embed_filters_by_song_ids(con, monkeypatch, tmp_path):
    """embed() only processes discovered songs whose IDs are in scope."""
    _install_embed_runtime_stubs()
    keep_path = tmp_path / "keep.mp3"
    skip_path = tmp_path / "skip.mp3"
    embed_song_raw = Mock(return_value=True)

    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
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
    monkeypatch.setattr(embed_mod, "_discover_audio", Mock(return_value=[song_path]))
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"bb": {"path": "model.onnx", "backbone_name": "bb-model"}})
    monkeypatch.setattr(embed_mod, "_embed_song_raw", embed_song_raw)
    monkeypatch.setattr(embed_mod, "_alive_it", _make_alive_it_stub())

    embed_mod.embed(con, backbones=["bb"])

    embed_song_raw.assert_called_once()
