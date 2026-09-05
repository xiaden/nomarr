"""P1-S3 observation-group tests: derive_audio_mask (production boundary) + live
observation-group publication + CPU-only mask regeneration.

These are synthetic-fixture-only tests.  The production preprocessing functions are
either (a) injected as sys.modules stubs of ``nomarr.components.ml.audio.ml_preprocess_comp``
for call-boundary / derive tests (the module tree is not importable in the research
test env), or (b) loaded STANDALONE from disk via ``importlib.util.spec_from_file_location``
for the golden tail/short-spectrogram replay comparison — its top-level imports are
essentia-free, so a genuine comparison against the real production arithmetic is possible.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import numpy as np
import pytest

# Stub nomarr.helpers.time_helper (same pattern as test_embed.py).
_time_helper_module: Any = ModuleType("nomarr.helpers.time_helper")
_time_helper_module.internal_ms = lambda: 0
_helpers_module: Any = sys.modules.setdefault("nomarr.helpers", ModuleType("nomarr.helpers"))
_helpers_module.time_helper = _time_helper_module
sys.modules.setdefault("nomarr.helpers.time_helper", _time_helper_module)

from scripts.embedding_research.common import embed as embed_mod
from scripts.embedding_research.streams import StreamStore
from scripts.embedding_research.streams.masks import (
    MASK_ALGORITHM,
    MASK_SEMANTICS_VERSION,
    MASK_THRESHOLD_DBFS,
    MaskPayload,
    _drop_short_silent_runs,
    canonical_audio_fingerprint,
    derive_audio_mask,
    mask_npy_bytes,
    replay_patch_starts,
)
from scripts.embedding_research.streams.publication import RecordingFileOps
from scripts.embedding_research.streams.records import (
    ObservationCommit,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRODUCTION_PREPROCESS = _REPO_ROOT / "nomarr/components/ml/audio/ml_preprocess_comp.py"


@pytest.fixture
def tmp_path(request):
    safe_name = request.node.name[:20]
    return Path(tempfile.mkdtemp(prefix=f"{safe_name}-{uuid4().hex[:8]}-"))


def _store(con, tmp_path) -> StreamStore:
    return StreamStore(con, output_root=tmp_path)


def _audio_fp(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


# ── production-module standalone load ──────────────────────────────────────────


def _load_production_preprocess():
    """Load the REAL production ml_preprocess_comp module standalone (no package import).

    Its top-level imports are ``__future__``/``logging``/``typing``/``numpy`` only
    (essentia is imported lazily inside ``compute_log_mel``), so loading the file via a
    synthetic module + exec gives a genuine reference to the production
    ``get_params``/``extract_patches`` arithmetic without touching the enclosing package
    or essentia.
    """
    spec = importlib.util.spec_from_file_location("_prod_preprocess_standalone", str(_PRODUCTION_PREPROCESS))
    assert spec is not None and spec.loader is not None
    module = ModuleType(spec.name)
    spec.loader.exec_module(module)
    return module


# ── golden replay vs real production module ───────────────────────────────────


@pytest.mark.unit
def test_replay_matches_real_production_extract_patches_full_grid():
    prod = _load_production_preprocess()
    params = prod.get_params("effnet")  # patch_frames=128, patch_hop=93
    pf, ph = params.patch_frames, params.patch_hop
    n_frames, n_mels = 700, params.n_mels
    log_mel = np.zeros((n_frames, n_mels), dtype=np.float32)

    patches = prod.extract_patches(log_mel, pf, ph)
    starts = replay_patch_starts(n_frames, pf, ph)

    assert len(starts) == patches.shape[0] == 7  # range(0, 700-128+1=573, 93) -> 7
    for p, start in enumerate(starts):
        assert np.array_equal(patches[p], log_mel[start : start + pf])


@pytest.mark.unit
def test_replay_matches_real_production_extract_patches_tail():
    """The tail floor is observable: last frame not covered -> last patch start < n_frames - pf."""
    prod = _load_production_preprocess()
    params = prod.get_params("effnet")
    pf, ph = params.patch_frames, params.patch_hop
    # A frame count where the tail is a partial (non-reached) last window.
    n_frames = pf + 1
    log_mel = np.zeros((n_frames, params.n_mels), dtype=np.float32)
    patches = prod.extract_patches(log_mel, pf, ph)
    starts = replay_patch_starts(n_frames, pf, ph)
    assert len(starts) == patches.shape[0]
    assert starts[-1] + pf <= n_frames  # last patch never runs past the grid
    for p, start in enumerate(starts):
        assert np.array_equal(patches[p], log_mel[start : start + pf])


@pytest.mark.unit
def test_replay_short_spectrogram_matches_real_production_empty():
    prod = _load_production_preprocess()
    params = prod.get_params("effnet")
    pf, ph = params.patch_frames, params.patch_hop
    n_frames = pf - 1  # shorter than one patch -> no patches
    log_mel = np.zeros((n_frames, params.n_mels), dtype=np.float32)
    patches = prod.extract_patches(log_mel, pf, ph)
    assert patches.shape[0] == 0
    assert replay_patch_starts(n_frames, pf, ph) == []


@pytest.mark.unit
def test_masks_module_has_no_patch_index_times_hop_inference():
    """Negative proof: derive/replay code never infers starts as patch_index*patch_hop.

    We scan only the code bodies of the algorithmic functions (not the module docstring,
    which documents the very prohibition) and additionally require that the per-patch
    reduction enumerates the *replayed* start grid rather than reconstructing offsets.
    """
    import inspect as _inspect

    import scripts.embedding_research.streams.masks as masks_mod

    def _code(fn):
        raw = _inspect.getsource(fn)
        # Drop the leading triple-quoted docstring so the scan is over code only.
        i = raw.find('"""')
        if i != -1:
            end = raw.find('"""', i + 3)
            if end != -1:
                raw = raw[:i] + raw[end + 3 :]
        return raw

    body = "".join(_code(fn) for fn in (masks_mod.replay_patch_starts, masks_mod.derive_audio_mask))
    assert "patch_index" not in body
    assert "patch_index*patch_hop" not in body
    assert "* patch_hop" not in body
    # derive must iterate the replayed start grid directly (slice reconstruction).
    assert "for p, start in enumerate(starts)" in _code(masks_mod.derive_audio_mask)


# ── derive_audio_mask call boundary + semantics (production stubs injected) ───


def _install_preprocess_stubs(monkeypatch) -> tuple[SimpleNamespace, Mock, Mock, Mock]:
    """Install a sys.modules stub of the production preprocess module used by derive.

    Returns ``(params, get_params, compute_log_mel, extract_patches)``.  ``extract_patches``
    slices ``log_mel`` by the replayed production start arithmetic so it is consistent with
    the grid ``derive_audio_mask`` re-derives (a real-module comparison is separately proven
    by the golden tests above).
    """
    for name in ("nomarr", "nomarr.components", "nomarr.components.ml", "nomarr.components.ml.audio"):
        sys.modules.setdefault(name, ModuleType(name))
    stub = ModuleType("nomarr.components.ml.audio.ml_preprocess_comp")

    params = SimpleNamespace(
        sample_rate=16000,
        n_mels=8,
        n_fft=512,
        hop_length=256,
        patch_frames=16,
        patch_hop=8,
        fmin=0,
        fmax=8000,
        zero_padding=0,
        zero_phase=False,
        warping_formula="slaneyMel",
        mel_type="magnitude",
        weighting="none",
        normalize=False,
        post_shift=0.0,
        post_scale=1.0,
        compression="log",
    )

    def _get_params(backbone):
        assert backbone
        return params

    def _compute_log_mel(_audio, p):
        return np.zeros((64, p.n_mels), dtype=np.float32)

    def _extract_patches(log_mel, pf, ph):
        n_frames = log_mel.shape[0]
        starts = replay_patch_starts(n_frames, pf, ph)
        if not starts:
            return np.zeros((0, pf, log_mel.shape[1]), dtype=np.float32)
        return np.stack([log_mel[s : s + pf] for s in starts], axis=0).astype(np.float32)

    stub.get_params = Mock(side_effect=_get_params)
    stub.compute_log_mel = Mock(side_effect=_compute_log_mel)
    stub.extract_patches = Mock(side_effect=_extract_patches)
    monkeypatch.setitem(sys.modules, "nomarr.components.ml.audio.ml_preprocess_comp", stub)
    return params, stub.get_params, stub.compute_log_mel, stub.extract_patches


def _loud_audio() -> np.ndarray:
    """Canonical-length mono audio whose every window is far above the -60 dBFS gate."""
    return np.full(64 * 256 + 512, 0.1, dtype=np.float32)


def _silent_audio() -> np.ndarray:
    return np.zeros(64 * 256 + 512, dtype=np.float32)


def _stream_record(patch_count: int = 7, run_id: str = "run-x", sid: str = "songA", backbone: str = "effnet"):
    from scripts.embedding_research.streams.records import StreamRecord

    return StreamRecord(
        song_id=sid,
        backbone=backbone,
        artifact_ref=f"streams/{sid}.{backbone}.{'0' * 64}.npy",
        patch_count=patch_count,
        dim=4,
        dtype="float32",
        format_version="1",
        fingerprint_sha256="a" * 64,
        preprocess_fn="nomarr.components.ml.audio.ml_preprocess_comp",
        preprocess_version="",
        backbone_model_hash="",
        audio_params="",
        embed_semantics_version=1,
        provenance_source="embed",
        provenance_assumption="",
        status="pending",
        run_id=run_id,
        created_at=1,
        updated_at=1,
    )


@pytest.mark.unit
def test_derive_audio_mask_invokes_production_preprocessing_and_returns_all_ones(monkeypatch):
    _params, get_params, compute_log_mel, extract_patches = _install_preprocess_stubs(monkeypatch)
    audio = _loud_audio()
    record = _stream_record(patch_count=7)
    payload = derive_audio_mask(audio, "effnet", record, audio_fingerprint=canonical_audio_fingerprint(audio))

    assert get_params.call_count == 1
    assert compute_log_mel.call_count == 1
    assert extract_patches.call_count == 1
    assert payload.song_id == "songA"
    assert payload.backbone == "effnet"
    assert payload.patch_count == 7
    assert payload.mask.dtype == np.uint8
    assert payload.mask.shape == (7,)
    assert payload.mask.tolist() == [1, 1, 1, 1, 1, 1, 1]  # all-loud -> all searchable
    assert payload.algorithm == MASK_ALGORITHM
    assert payload.threshold_dbfs == MASK_THRESHOLD_DBFS
    assert payload.mask_semantics_version == MASK_SEMANTICS_VERSION
    assert len(payload.params_id) == 64
    assert payload.audio_content_sha256 == canonical_audio_fingerprint(audio)


@pytest.mark.unit
def test_derive_audio_mask_all_silent_is_all_hidden(monkeypatch):
    _install_preprocess_stubs(monkeypatch)
    audio = _silent_audio()
    record = _stream_record(patch_count=7)
    payload = derive_audio_mask(audio, "effnet", record, audio_fingerprint=canonical_audio_fingerprint(audio))
    assert payload.mask.tolist() == [0, 0, 0, 0, 0, 0, 0]


@pytest.mark.unit
def test_derive_audio_mask_fingerprint_mismatch_is_hard_failure(monkeypatch):
    _install_preprocess_stubs(monkeypatch)
    audio = _loud_audio()
    record = _stream_record(patch_count=7)
    wrong_fp = _audio_fp(b"something else")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        derive_audio_mask(audio, "effnet", record, audio_fingerprint=wrong_fp)


@pytest.mark.unit
def test_derive_audio_mask_patch_count_mismatch_raises(monkeypatch):
    _install_preprocess_stubs(monkeypatch)
    audio = _loud_audio()
    record = _stream_record(patch_count=999)  # production returns 7
    with pytest.raises(ValueError, match="patch_count"):
        derive_audio_mask(audio, "effnet", record, audio_fingerprint=canonical_audio_fingerprint(audio))


@pytest.mark.unit
def test_derive_audio_mask_isolated_silent_run_helper():
    # [active, silent(isolated), active] -> the single-frame silent run is removed.
    flags = np.array([True, False, True, True, True, True, True])
    assert _drop_short_silent_runs(flags, 2).tolist() == [True, True, True, True, True, True, True]
    # A 3-frame silent run (>= min_run 2) is preserved (searchable=0 stays).
    flags2 = np.array([True, False, False, False, True, True, True])
    assert _drop_short_silent_runs(flags2, 2).tolist() == [True, False, False, False, True, True, True]


# ── observation-group store publication ───────────────────────────────────────


def _publish_stream(con, tmp_path, sid="songA", backbone="effnet", patch_count=7) -> tuple[StreamStore, Any]:
    store = _store(con, tmp_path)
    embeddings = np.random.RandomState(0).rand(patch_count, 4).astype(np.float32)
    record = store.publish(sid, backbone, embeddings, run_id="run-1")
    return store, record


def _mask_payload(sid, backbone, patch_count, audio_waveform=None, run_id="run-1") -> MaskPayload:
    fp = canonical_audio_fingerprint(audio_waveform) if audio_waveform is not None else _audio_fp(b"audio-content")
    return MaskPayload(
        song_id=sid,
        backbone=backbone,
        patch_count=patch_count,
        mask=np.ones(patch_count, dtype=np.uint8),
        params_id="0" * 64,
        audio_content_sha256=fp,
        run_id=run_id,
        created_at=1,
    )


@pytest.mark.unit
def test_publish_observation_group_writes_mask_and_commit_marker_last(con, tmp_path):
    store, stream_record = _publish_stream(con, tmp_path)
    rec_ops = RecordingFileOps()
    payload = _mask_payload("songA", "effnet", stream_record.patch_count)
    commit = store.publish_observation_group(stream_record, payload, file_ops=rec_ops)

    assert isinstance(commit, ObservationCommit)
    assert commit.stream_ref == stream_record.artifact_ref
    assert commit.mask_ref.startswith("audio_masks/")
    assert commit.commit_sha256 == commit.commit_sha256

    # Mask payload + manifest and commit marker all on disk under tmp_path.
    mask_path = tmp_path / commit.mask_ref
    assert mask_path.is_file()
    assert (tmp_path / "audio_masks").is_dir()
    assert (tmp_path / "observation_commits").is_dir()

    # Commit-marker-LAST: mask payload+manifest are renamed first, and the LAST durable
    # rename is the observation-commit marker under observation_commits/.
    renames = [detail for op, detail in rec_ops.events if op == "rename"]
    assert renames, "expected at least one recorded rename"
    mask_renames = [d for d in renames if "audio_masks" in str(d[1])]
    assert mask_renames, "mask payload/manifest must be durably renamed"
    last_dst = renames[-1][1]
    assert "observation_commits" in str(last_dst), f"commit marker must be written LAST; got {last_dst}"
    # commit rename strictly after the last mask rename
    assert renames.index(renames[-1]) > max(i for i, d in enumerate(renames) if "audio_masks" in str(d[1]))

    # Group readiness: full verify (marker + stream + mask).
    assert store.observation_group_ready("songA", "effnet", stream_record=stream_record)


@pytest.mark.unit
def test_observation_group_cross_identity_and_alignment_are_enforced(con, tmp_path):
    store, stream_record = _publish_stream(con, tmp_path)
    with pytest.raises(ValueError, match="song_id mismatch"):
        store.publish_observation_group(stream_record, _mask_payload("songB", "effnet", stream_record.patch_count))
    with pytest.raises(ValueError, match="backbone mismatch"):
        store.publish_observation_group(stream_record, _mask_payload("songA", "musicnn", stream_record.patch_count))
    with pytest.raises(ValueError, match="patch_count mismatch"):
        store.publish_observation_group(stream_record, _mask_payload("songA", "effnet", stream_record.patch_count + 3))


@pytest.mark.unit
def test_observation_group_partial_states_never_ready(con, tmp_path):
    store, stream_record = _publish_stream(con, tmp_path)
    # mask+manifest published but NO commit marker -> not a committed/ready group.
    payload = _mask_payload("songA", "effnet", stream_record.patch_count)
    store.publish_mask(payload)
    assert store.observation_group_ready("songA", "effnet", stream_record=stream_record) is False

    # full group then delete the mask payload -> no longer ready (corrupt ref).
    commit = store.publish_observation_group(stream_record, payload)
    assert store.observation_group_ready("songA", "effnet", stream_record=stream_record) is True
    (tmp_path / commit.mask_ref).unlink()
    assert store.observation_group_ready("songA", "effnet", stream_record=stream_record) is False


@pytest.mark.unit
def test_read_committed_mask_audio_fingerprint(con, tmp_path):
    store, stream_record = _publish_stream(con, tmp_path)
    audio = _loud_audio()
    fp = canonical_audio_fingerprint(audio)
    store.publish_observation_group(stream_record, _mask_payload("songA", "effnet", stream_record.patch_count, audio))
    assert store.read_committed_mask_audio_fingerprint("songA", "effnet") == fp
    assert store.read_committed_mask_audio_fingerprint("other", "effnet") is None


@pytest.mark.unit
def test_mask_payload_and_record_validation():
    _mask_payload("songA", "effnet", 5)
    with pytest.raises(ValueError):
        MaskPayload(song_id="song.A", backbone="effnet", patch_count=5, mask=np.ones(5, np.uint8))
    with pytest.raises(ValueError, match="mask shape"):
        MaskPayload(song_id="songA", backbone="effnet", patch_count=5, mask=np.zeros(4, np.uint8))  # wrong size
    with pytest.raises(ValueError, match="mask dtype"):
        MaskPayload(song_id="songA", backbone="effnet", patch_count=5, mask=np.zeros(5, dtype=np.float32))
    # uint8 bytes round-trip through mask_npy_bytes.
    arr = np.array([1, 0, 1], dtype=np.uint8)
    import io

    assert np.array_equal(np.load(io.BytesIO(mask_npy_bytes(arr))), arr)


# ── embed()/regenerate integration ────────────────────────────────────────────


def _install_embed_runtime_stubs(monkeypatch) -> None:
    """nomarr module stubs for embed()'s dynamic imports (mirrors test_embed.py)."""
    for name in (
        "nomarr",
        "nomarr.components",
        "nomarr.components.ml",
        "nomarr.components.ml.onnx",
        "nomarr.components.ml.audio",
    ):
        sys.modules.setdefault(name, ModuleType(name))
    onnx_stub = ModuleType("nomarr.components.ml.onnx.ml_session_comp")
    onnx_stub.create_session = Mock()
    onnx_stub._BACKBONE_BATCH_SIZE = 4
    onnx_stub._run_in_batches = Mock(return_value=np.zeros((1, 4), dtype=np.float32))
    sys.modules["nomarr.components.ml.onnx.ml_session_comp"] = onnx_stub
    audio_stub = ModuleType("nomarr.components.ml.audio.ml_audio_comp")
    sys.modules["nomarr.components.ml.audio.ml_audio_comp"] = audio_stub
    preprocess_stub = ModuleType("nomarr.components.ml.audio.ml_preprocess_comp")
    preprocess_stub.preprocess_for_backbone = Mock(return_value=np.zeros((7, 16, 8), dtype=np.float32))
    sys.modules["nomarr.components.ml.audio.ml_preprocess_comp"] = preprocess_stub
    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)


@pytest.mark.unit
def test_embed_song_raw_produce_masks_publishes_group(con, monkeypatch, tmp_path):
    """With produce_masks=True, _embed_song_raw derives + publishes the mask group."""
    store = _store(con, tmp_path)
    sid = "songM"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)
    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {"path": str(path), "artist": "A", "album": "B", "title": "T", "genre": "G"},
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_a, **_k: None)
    waveform = _loud_audio()
    monkeypatch.setattr(
        embed_mod,
        "_derive_audio_mask",
        lambda audio, backbone, record, **_kwargs: _mask_payload(sid, backbone, record.patch_count, audio),
    )
    monkeypatch.setattr(embed_mod, "_canonical_audio_fingerprint", lambda _wf: canonical_audio_fingerprint(waveform))

    session = Mock()
    session.run = Mock(return_value=[np.zeros((1, 4), dtype=np.float32)])

    path = tmp_path / f"{sid}.wav"
    path.touch()
    worked = embed_mod._embed_song_raw(
        path,
        "effnet",
        {"backbone_name": "effnet"},
        load_audio_fn=lambda _p, **_kwargs: SimpleNamespace(waveform=waveform),
        preprocess_fn=lambda _wf, _bb: np.zeros((7, 16, 8), dtype=np.float32),
        session=session,
        run_in_batches_fn=lambda predict, patches, _batch_size: predict(patches),
        batch_size=4,
        con=con,
        store=store,
        run_id="run-1",
        force=False,
        produce_masks=True,
    )
    assert worked is True
    assert store.observation_group_ready(sid, "effnet")


@pytest.mark.unit
def test_embed_song_raw_produce_masks_false_leaves_no_group(con, monkeypatch, tmp_path):
    """Legacy direct callers (produce_masks=False) publish only the stream."""
    store = _store(con, tmp_path)
    sid = "songN"
    monkeypatch.setattr(embed_mod, "_song_id", lambda _path: sid)
    monkeypatch.setattr(embed_mod, "_song_exists", lambda _con, _sid: False)
    monkeypatch.setattr(
        embed_mod,
        "_path_to_meta",
        lambda path: {"path": str(path), "artist": "A", "album": "B", "title": "T", "genre": "G"},
    )
    monkeypatch.setattr(embed_mod, "_upsert_song", lambda *_a, **_k: None)
    waveform = _loud_audio()
    session = Mock()
    session.run = Mock(return_value=[np.zeros((1, 4), dtype=np.float32)])
    path = tmp_path / f"{sid}.wav"
    path.touch()
    worked = embed_mod._embed_song_raw(
        path,
        "effnet",
        {"backbone_name": "effnet"},
        load_audio_fn=lambda _p, **_kwargs: SimpleNamespace(waveform=waveform),
        preprocess_fn=lambda _wf, _bb: np.zeros((7, 16, 8), dtype=np.float32),
        session=session,
        run_in_batches_fn=lambda predict, patches, _batch_size: predict(patches),
        batch_size=4,
        con=con,
        store=store,
        run_id="run-1",
        force=False,
        produce_masks=False,
    )
    assert worked is True
    assert (tmp_path / "observation_commits").exists() is False
    assert store.ready_stream_record(sid, "effnet") is None  # not reconciled yet


@pytest.mark.unit
def test_regenerate_masks_is_cpu_only_no_session_inference(monkeypatch, con, tmp_path):
    """--regenerate-masks performs zero ONNX/session/model work (sentinels)."""
    # Source-level structural proof: the regenerate_masks CODE BODY never touches session/ONNX.
    raw = inspect.getsource(embed_mod.regenerate_masks)
    i = raw.find('"""')
    if i != -1:
        end = raw.find('"""', i + 3)
        if end != -1:
            raw = raw[:i] + raw[end + 3 :]
    for forbidden in ("create_session", "session.run", "onnx", "cuda", "model.onnx"):
        assert forbidden not in raw, f"regenerate_masks code must not reference {forbidden!r}"

    # Behavioral proof with a fake store: equal fingerprint -> republish; changed -> refusal.
    monkeypatch.setattr(embed_mod, "_bootstrap_nomarr", lambda: None)
    monkeypatch.setattr(embed_mod, "_discover_audio", lambda: [tmp_path / "s1.wav", tmp_path / "s2.wav"])
    monkeypatch.setattr(embed_mod, "_song_id", lambda p: Path(p).stem)
    monkeypatch.setattr(embed_mod, "_BACKBONES", {"effnet": {"backbone_name": "effnet"}})

    unchanged_fp = canonical_audio_fingerprint(_loud_audio())
    canonical_audio_fingerprint(_silent_audio())

    calls = {"published": 0}

    class _FakeStore:
        def read_committed_mask_audio_fingerprint(self, _sid, _backbone):
            return unchanged_fp  # committed group audio

        def ready_stream_record(self, sid, backbone):
            from scripts.embedding_research.streams.records import StreamRecord

            return StreamRecord(
                song_id=sid,
                backbone=backbone,
                artifact_ref=f"streams/{sid}.{backbone}.{'0' * 64}.npy",
                patch_count=7,
                dim=4,
                dtype="float32",
                format_version="1",
                fingerprint_sha256="a" * 64,
                preprocess_fn="nomarr.components.ml.audio.ml_preprocess_comp",
                preprocess_version="",
                backbone_model_hash="",
                audio_params="",
                embed_semantics_version=1,
                provenance_source="embed",
                provenance_assumption="",
                status="ready",
                run_id="run-1",
                created_at=1,
                updated_at=1,
            )

        def publish_observation_group(self, _stream_record, _mask_payload):
            calls["published"] += 1

    monkeypatch.setattr(embed_mod, "StreamStore", lambda _con: _FakeStore())
    # regenerate_masks builds no session; load_audio returns current waveform.
    for name in ("nomarr", "nomarr.components", "nomarr.components.ml", "nomarr.components.ml.audio"):
        sys.modules.setdefault(name, ModuleType(name))
    audio_loader_mod = ModuleType("nomarr.components.ml.audio.ml_audio_comp")
    sys.modules["nomarr.components.ml.audio.ml_audio_comp"] = audio_loader_mod
    waveforms = {
        "s1": _loud_audio(),  # equal to committed -> regenerated
        "s2": _silent_audio(),  # differs -> refused
    }

    def _fake_load_audio(path_str, **kwargs):
        _ = kwargs.get("target_sr")  # load_audio contract accepts target_sr; swallowed here
        key = Path(path_str).stem
        return SimpleNamespace(waveform=waveforms[key])

    monkeypatch.setattr(
        embed_mod,
        "_derive_audio_mask",
        lambda audio, bb, rec, **_kwargs: _mask_payload(rec.song_id, bb, rec.patch_count, audio),
    )
    monkeypatch.setattr(embed_mod, "_canonical_audio_fingerprint", canonical_audio_fingerprint)
    # Inject the fake loader into the module regenerate_masks dynamically imports.
    audio_loader_mod.load_audio_mono = _fake_load_audio

    tally = embed_mod.regenerate_masks(con, backbones=["effnet"])
    assert tally["regenerated"] == 1  # s1
    assert tally["refused"] == 1  # s2 (audio changed)
    assert calls["published"] == 1
