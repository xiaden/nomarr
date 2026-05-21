"""Audio feature extraction and head inference."""

from __future__ import annotations

from pathlib import Path as _Path
from typing import Any as _Any
from typing import cast as _cast

import numpy as _np

from nomarr.components.ml.audio import load_audio_mono as _load_audio_mono

from ._constants import _BACKBONE_SR

try:
    import librosa as _librosa  # type: ignore[import]

    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False


def _extract_patch_features(path: _Path | str, n_patches: int) -> list[dict] | None:
    if not _HAS_LIBROSA or n_patches < 1:
        return None

    try:
        result = _load_audio_mono(str(path), target_sr=_BACKBONE_SR)
        y = result.waveform
        sr = result.sample_rate
    except Exception:
        return None

    n_frames = len(y)
    if n_frames == 0:
        return None

    hop = 512
    n_fft = 2048
    rms_frames = _librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop)[0]
    sc_frames = _librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=n_fft, hop_length=hop)[0]
    os_frames = _librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    chroma = _librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop)

    n_feat_frames = len(rms_frames)
    features: list[dict] = []
    for patch_idx in range(n_patches):
        f_start = round(patch_idx * n_feat_frames / n_patches)
        f_end = round((patch_idx + 1) * n_feat_frames / n_patches)
        f_end = max(f_end, f_start + 1)
        f_end = min(f_end, n_feat_frames)
        features.append(
            {
                "rms": float(rms_frames[f_start:f_end].mean()),
                "spectral_centroid": float(sc_frames[f_start:f_end].mean()),
                "onset_strength": float(os_frames[f_start:f_end].mean()),
                "chroma_key": int(chroma[:, f_start:f_end].mean(axis=1).argmax()),
            }
        )
    return features


def _run_head_on_vec(session, vec: _np.ndarray) -> _np.ndarray:
    inp = vec[None, :].astype(_np.float32)
    outputs = _cast("_Any", session.run(["activations"], {"embeddings": inp}))
    if not outputs:
        raise RuntimeError("Head session returned no activations")
    return _np.asarray(outputs[0][0], dtype=_np.float32)


def _run_head_batch(session, vecs: _np.ndarray) -> _np.ndarray:
    """Run a head model on a batch of vectors.

    Args:
        session: ONNX InferenceSession for the head model.
        vecs: Float32 array of shape [N, D].

    Returns:
        Float32 array of shape [N, n_classes].
    """
    inp = vecs.astype(_np.float32)
    outputs = _cast("_Any", session.run(["activations"], {"embeddings": inp}))
    if not outputs:
        raise RuntimeError("Head session returned no activations")
    return _np.asarray(outputs[0], dtype=_np.float32)
