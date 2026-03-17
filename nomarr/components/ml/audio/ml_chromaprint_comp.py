"""Chromaprint (audio fingerprinting) component for move detection.

Computes content-based audio fingerprints using spectral analysis.
These fingerprints are used to detect when files have been moved/renamed
while preserving their audio content.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np
from scipy.signal import windows

logger = logging.getLogger(__name__)

# Pre-compute the Hann window once at module level (deterministic, zero cost).
_HANN_2048: np.ndarray = windows.hann(2048, sym=True).astype(np.float32)


def compute_chromaprint(waveform: np.ndarray, sample_rate: int) -> str:
    """Compute audio fingerprint (chromaprint) from waveform.

    Uses spectral analysis to create a content-based hash that:
    - Is identical for the same audio content
    - Differs for different recordings
    - Is robust to metadata changes

    The spectral pipeline is numerically equivalent to the former Essentia
    Windowing(type="hann", size=2048) + Spectrum(size=2048) implementation:
    a Hann-windowed frame fed to rfft, producing 1025 magnitude bins.

    This fingerprint is used for move detection: if a file disappears and a new
    file with the same chromaprint appears, it's likely the same file moved.

    Args:
        waveform: Audio waveform as float32 numpy array (mono)
        sample_rate: Sample rate in Hz

    Returns:
        Hexadecimal hash string (32 characters, MD5)

    """
    try:
        # Use first 60 seconds for fingerprinting (balance speed vs accuracy)
        max_samples = 60 * sample_rate
        audio_chunk = waveform[:max_samples] if len(waveform) > max_samples else waveform

        # Extract spectral frames (hop 512 samples = ~32ms at 16 kHz)
        hop_size = 512
        frame_size = 2048
        num_frames = max(0, (len(audio_chunk) - frame_size) // hop_size)

        # Limit to 200 frames to keep fingerprint size reasonable
        num_frames = min(num_frames, 200)

        spectra = []
        for i in range(num_frames):
            start = i * hop_size
            end = start + frame_size
            if end > len(audio_chunk):
                break

            frame = np.asarray(audio_chunk[start:end], dtype=np.float32)
            # Hann window (equivalent to Essentia Windowing(type="hann", size=2048))
            windowed = frame * _HANN_2048
            # Magnitude spectrum (equivalent to Essentia Spectrum(size=2048))
            # rfft on 2048 samples -> 1025 bins
            spec = np.abs(np.fft.rfft(windowed, n=2048)).astype(np.float32)
            spectra.append(spec)

        # Convert to numpy array and compute hash
        if not spectra:
            # Audio too short, use waveform itself
            fingerprint_data = waveform.tobytes()
        else:
            spectra_array = np.array(spectra, dtype=np.float32)

            # Quantize to int16 for robustness against tiny float variations.
            # Scale to full int16 range, then clip and convert.
            spectra_max = np.max(np.abs(spectra_array))
            if spectra_max > 0:
                scaled = (spectra_array / spectra_max) * 32767.0
                quantized = np.clip(scaled, -32768, 32767).astype(np.int16)
            else:
                quantized = np.zeros_like(spectra_array, dtype=np.int16)

            fingerprint_data = quantized.tobytes()

        # MD5 hash of spectral fingerprint
        return hashlib.md5(fingerprint_data).hexdigest()

    except Exception as e:
        logger.exception(f"Failed to compute chromaprint: {e}")
        # Fallback: hash the raw waveform (less robust but still works)
        return hashlib.md5(waveform.tobytes()).hexdigest()
