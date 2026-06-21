"""Chromaprint (audio fingerprinting) component for move detection.

Computes content-based audio fingerprints using the Chromaprint algorithm
via pyacoustid (libchromaprint). These fingerprints are used to detect when
files have been moved/renamed while preserving their audio content.
"""

from __future__ import annotations

import logging

import chromaprint
import numpy as np

logger = logging.getLogger(__name__)


def compute_chromaprint(waveform: np.ndarray, sample_rate: int) -> str:
    """Compute audio fingerprint (chromaprint) from waveform.

    Uses the Chromaprint algorithm (via pyacoustid / libchromaprint) to create
    a content-based fingerprint that:
    - Is identical for the same audio content
    - Differs for different recordings
    - Is robust to metadata changes

    The float32 waveform is converted to int16 PCM bytes as required by
    libchromaprint, then fingerprinted. Only the first 60 seconds of audio
    are used to keep fingerprinting fast.

    This fingerprint is used for move detection: if a file disappears and a new
    file with the same chromaprint appears, it's likely the same file moved.

    Args:
        waveform: Audio waveform as float32 numpy array (mono, from load_audio_mono)
        sample_rate: Sample rate in Hz

    Returns:
        Chromaprint fingerprint string

    """
    try:
        # Use first 60 seconds for fingerprinting (balance speed vs accuracy)
        max_samples = 60 * sample_rate
        audio_chunk = waveform[:max_samples] if len(waveform) > max_samples else waveform

        # Convert float32 waveform to int16 PCM bytes as required by libchromaprint
        pcm_bytes = np.clip(audio_chunk * 32767, -32768, 32767).astype(np.int16).tobytes()

        # Use chromaprint.Fingerprinter (pyacoustid's ctypes wrapper around libchromaprint)
        fingerprinter = chromaprint.Fingerprinter()
        fingerprinter.start(sample_rate, 1)  # mono
        fingerprinter.feed(pcm_bytes)
        fingerprint_bytes: bytes = fingerprinter.finish()

        return fingerprint_bytes.decode("ascii")

    except Exception as e:
        logger.exception(f"Failed to compute chromaprint: {e}")
        # Fallback: return empty string instead of raising
        return ""
