"""Backbone-specific mel spectrogram and patch extraction for ONNX inference.

Essentia's TensorflowPredict* classes perform mel spectrogram computation and
overlapping patch extraction internally (in C++).  With ONNX these steps run
externally in Python/NumPy before the session call.

Exact essentia parameters verified from TensorflowInputMusiCNN.cpp and
TensorflowInputVGGish.cpp upstream source:

  effnet   SR=16000  n_mels=96  n_fft=512  hop=256  patch=128f  hop_patches=93   (MusiCNN-style)
  musicnn  SR=16000  n_mels=96  n_fft=512  hop=256  patch=187f  hop_patches=128  (MusiCNN-style)
  vggish   SR=16000  n_mels=64  n_fft=400  hop=160  patch=96f   hop_patches=96   (VGGish-style, non-overlapping)
  yamnet   SR=16000  n_mels=64  n_fft=400  hop=160  patch=96f   hop_patches=96   (VGGish-style, non-overlapping)

All backbones expect float32 input; output shapes are [n_patches, patch_frames, n_mels].
"""

from __future__ import annotations

import logging
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class BackbonePreprocessParams(NamedTuple):
    """Static preprocessing parameters for a single backbone."""

    sample_rate: int
    n_mels: int
    n_fft: int            # Windowing frameSize / FrameCutter frameSize
    hop_length: int
    patch_frames: int     # number of mel frames per patch
    patch_hop: int        # mel-frame stride between patches
    fmin: float           # MelBands lowFrequencyBound
    fmax: float           # MelBands highFrequencyBound
    # windowing fields
    zero_padding: int     # Windowing zeroPadding (0 for MusiCNN, 112 for VGGish)
    zero_phase: bool      # Windowing zeroPhase (True for MusiCNN, False for VGGish)
    # mel band fields
    warping_formula: str  # MelBands warpingFormula ("slaneyMel" | "htkMel")
    mel_type: str         # MelBands type ("power" | "magnitude")
    weighting: str        # MelBands weighting ("linear" | "warping")
    normalize: str        # MelBands normalize ("unit_tri" | "unit_max")
    # compression fields
    post_shift: float     # UnaryOperator[0] shift: f(scale * x + shift)
    post_scale: float     # UnaryOperator[0] scale: f(scale * x + shift)
    compression: str      # UnaryOperator[1] type ("log10" | "log")


_PARAMS: dict[str, BackbonePreprocessParams] = {
    # effnet / discogs-effnet  (MusiCNN-style: log10(10000 * mel + 1))
    "effnet": BackbonePreprocessParams(
        sample_rate=16000,
        n_mels=96,
        n_fft=512,
        hop_length=256,
        patch_frames=128,
        patch_hop=93,
        fmin=0.0,
        fmax=8000.0,
        zero_padding=0,
        zero_phase=True,
        warping_formula="slaneyMel",
        mel_type="power",
        weighting="linear",
        normalize="unit_tri",
        post_shift=1.0,
        post_scale=10000.0,
        compression="log10",
    ),
    # musicnn / msd-musicnn  (MusiCNN-style: log10(10000 * mel + 1))
    "musicnn": BackbonePreprocessParams(
        sample_rate=16000,
        n_mels=96,
        n_fft=512,
        hop_length=256,
        patch_frames=187,
        patch_hop=128,
        fmin=0.0,
        fmax=8000.0,
        zero_padding=0,
        zero_phase=True,
        warping_formula="slaneyMel",
        mel_type="power",
        weighting="linear",
        normalize="unit_tri",
        post_shift=1.0,
        post_scale=10000.0,
        compression="log10",
    ),
    # vggish / audioset-vggish  (VGGish-style: log(mel + 0.01))
    "vggish": BackbonePreprocessParams(
        sample_rate=16000,
        n_mels=64,
        n_fft=400,
        hop_length=160,
        patch_frames=96,
        patch_hop=96,
        fmin=125.0,
        fmax=7500.0,
        zero_padding=112,
        zero_phase=False,
        warping_formula="htkMel",
        mel_type="magnitude",
        weighting="warping",
        normalize="unit_max",
        post_shift=0.01,
        post_scale=1.0,
        compression="log",
    ),
    # yamnet / audioset-yamnet  (VGGish-style: same spectrogram as vggish)
    "yamnet": BackbonePreprocessParams(
        sample_rate=16000,
        n_mels=64,
        n_fft=400,
        hop_length=160,
        patch_frames=96,
        patch_hop=96,
        fmin=125.0,
        fmax=7500.0,
        zero_padding=112,
        zero_phase=False,
        warping_formula="htkMel",
        mel_type="magnitude",
        weighting="warping",
        normalize="unit_max",
        post_shift=0.01,
        post_scale=1.0,
        compression="log",
    ),
}


def get_params(backbone: str) -> BackbonePreprocessParams:
    """Return preprocessing parameters for *backbone*.

    Raises:
        ValueError: If *backbone* is not recognised.
    """
    try:
        return _PARAMS[backbone]
    except KeyError:
        msg = f"Unknown backbone '{backbone}'. Known: {sorted(_PARAMS)}"
        raise ValueError(msg) from None


def compute_log_mel(
    waveform: np.ndarray,
    params: BackbonePreprocessParams,
) -> np.ndarray:
    """Compute a log-mel spectrogram from a mono float32 waveform.

    Uses essentia standard algorithms (Windowing \u2192 Spectrum \u2192 MelBands \u2192
    UnaryOperator) with exact parameters verified from
    TensorflowInputMusiCNN.cpp and TensorflowInputVGGish.cpp upstream source.

    Args:
        waveform: 1-D float32 array at ``params.sample_rate``.
        params: Preprocessing parameters for the target backbone.

    Returns:
        Float32 array of shape ``[n_frames, n_mels]``.
    """
    fft_size = params.n_fft + params.zero_padding

    import essentia.standard as _estd  # lazy import

    windowing = _estd.Windowing(
        size=params.n_fft,
        normalized=False,
        zeroPadding=params.zero_padding,
        zeroPhase=params.zero_phase,
    )
    spectrum = _estd.Spectrum(size=fft_size)
    mel_bands = _estd.MelBands(
        inputSize=fft_size // 2 + 1,
        numberBands=params.n_mels,
        sampleRate=float(params.sample_rate),
        lowFrequencyBound=params.fmin,
        highFrequencyBound=params.fmax,
        warpingFormula=params.warping_formula,
        type=params.mel_type,
        weighting=params.weighting,
        normalize=params.normalize,
    )
    linear_compress = _estd.UnaryOperator(
        type="identity",
        shift=params.post_shift,
        scale=params.post_scale,
    )
    log_compress = _estd.UnaryOperator(type=params.compression)

    audio = waveform.astype(np.float32)
    frames: list[np.ndarray] = []
    pos = 0
    while pos + params.n_fft <= len(audio):
        frame = audio[pos : pos + params.n_fft]
        windowed = windowing(frame)
        spec = spectrum(windowed)
        mel = mel_bands(spec)
        mel_linear = linear_compress(mel)
        mel_log = log_compress(mel_linear)
        frames.append(mel_log)
        pos += params.hop_length

    if not frames:
        return np.empty((0, params.n_mels), dtype=np.float32)

    return np.asarray(frames, dtype=np.float32)


def extract_patches(
    log_mel: np.ndarray,
    patch_frames: int,
    patch_hop: int,
) -> np.ndarray:
    """Slice a log-mel spectrogram into overlapping patches.

    Args:
        log_mel: Float32 array of shape ``[n_frames, n_mels]``.
        patch_frames: Number of mel frames per patch.
        patch_hop: Mel-frame stride between patch start positions.

    Returns:
        Float32 array of shape ``[n_patches, patch_frames, n_mels]``.
        Returns an empty array with shape ``[0, patch_frames, n_mels]`` if
        the spectrogram is shorter than one patch.
    """
    n_frames, n_mels = log_mel.shape

    if n_frames < patch_frames:
        logger.debug(
            "[preprocess] spectrogram too short for one patch (%d < %d frames)",
            n_frames,
            patch_frames,
        )
        return np.empty((0, patch_frames, n_mels), dtype=np.float32)

    starts = list(range(0, n_frames - patch_frames + 1, patch_hop))
    patches: np.ndarray = np.stack(
        [log_mel[s : s + patch_frames] for s in starts],
        axis=0,
    )  # [n_patches, patch_frames, n_mels]

    return patches.astype(np.float32)


def preprocess_for_backbone(
    waveform: np.ndarray,
    backbone: str,
) -> np.ndarray:
    """End-to-end preprocessing: waveform \u2192 patches ready for ONNX inference.

    Combines :func:`compute_log_mel` and :func:`extract_patches` using the
    validated parameters for *backbone*.

    Args:
        waveform: Mono float32 waveform at 16 kHz.
        backbone: One of ``effnet``, ``musicnn``, ``vggish``, ``yamnet``.

    Returns:
        Float32 array of shape ``[n_patches, patch_frames, n_mels]``.

    Raises:
        ValueError: If *backbone* is not recognised.
    """
    params = get_params(backbone)
    log_mel = compute_log_mel(waveform, params)
    patches = extract_patches(log_mel, params.patch_frames, params.patch_hop)
    logger.debug(
        "[preprocess] %s: waveform=%d samples \u2192 mel=%s \u2192 patches=%s",
        backbone,
        len(waveform),
        log_mel.shape,
        patches.shape,
    )
    return patches
