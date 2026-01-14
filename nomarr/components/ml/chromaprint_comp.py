"""
Chromaprint (audio fingerprinting) component for move detection.

Computes content-based audio fingerprints using spectral analysis.
These fingerprints are used to detect when files have been moved/renamed
while preserving their audio content.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia

logger = logging.getLogger(__name__)


def compute_chromaprint(waveform: np.ndarray, sample_rate: int) -> str:
    """
    Compute audio fingerprint (chromaprint) from waveform.

    Uses Essentia's spectral analysis to create a content-based hash that:
    - Is identical for the same audio content
    - Differs for different recordings
    - Is robust to metadata changes

    This fingerprint is used for move detection: if a file disappears and a new
    file with the same chromaprint appears, it's likely the same file moved.

    Args:
        waveform: Audio waveform as float32 numpy array (mono)
        sample_rate: Sample rate in Hz

    Returns:
        Hexadecimal hash string (32 characters, MD5)

    Raises:
        RuntimeError: If Essentia is not available
    """
    backend_essentia.require()

    try:
        # Import Essentia algorithms
        from essentia.standard import Spectrum, Windowing  # type: ignore[import-untyped]

        # Use first 60 seconds for fingerprinting (balance speed vs accuracy)
        max_samples = 60 * sample_rate
        y = waveform[:max_samples] if len(waveform) > max_samples else waveform

        # Initialize Essentia algorithms
        windowing = Windowing(type="hann", size=2048)
        spectrum = Spectrum(size=2048)

        # Extract spectral frames (hop 512 samples = ~32ms at 16kHz)
        hop_size = 512
        frame_size = 2048
        num_frames = max(0, (len(y) - frame_size) // hop_size)

        # Limit to 200 frames to keep fingerprint size reasonable
        num_frames = min(num_frames, 200)

        spectra = []
        for i in range(num_frames):
            start = i * hop_size
            end = start + frame_size
            if end > len(y):
                break

            frame = y[start:end]
            windowed = windowing(frame)
            spec = spectrum(windowed)
            spectra.append(spec)

        # Convert to numpy array and compute hash
        if not spectra:
            # Audio too short, use waveform itself
            fingerprint_data = waveform.tobytes()
        else:
            spectra_array = np.array(spectra, dtype=np.float32)

            # Quantize to int16 for robustness against tiny float variations
            # Scale to use full int16 range, then clip and convert
            # This makes fingerprint less sensitive to float precision issues
            spectra_max = np.max(np.abs(spectra_array))
            if spectra_max > 0:
                scaled = (spectra_array / spectra_max) * 32767.0  # Scale to int16 range
                quantized = np.clip(scaled, -32768, 32767).astype(np.int16)
            else:
                quantized = np.zeros_like(spectra_array, dtype=np.int16)

            fingerprint_data = quantized.tobytes()

        # MD5 hash of spectral fingerprint
        return hashlib.md5(fingerprint_data).hexdigest()

    except Exception as e:
        logger.error(f"Failed to compute chromaprint: {e}")
        # Fallback: hash the raw waveform (less robust but still works)
        return hashlib.md5(waveform.tobytes()).hexdigest()
