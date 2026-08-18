"""Chromaprint (audio fingerprinting) component for move detection.

Computes content-based audio fingerprints using the AcoustID Chromaprint library.
These fingerprints are used to detect when files have been moved/renamed
while preserving their audio content.
"""

from __future__ import annotations

import logging

import acoustid
import numpy as np

logger = logging.getLogger(__name__)


def compute_chromaprint(waveform: np.ndarray, sample_rate: int) -> str:
    """Compute audio fingerprint (chromaprint) from waveform.

    Uses the AcoustID Chromaprint library for content-based audio fingerprinting.
    Fingerprints are base64-encoded strings that are:
    - Identical for the same audio content
    - Different for different recordings
    - Robust to metadata changes

    This fingerprint is used for move detection: if a file disappears and a new
    file with the same chromaprint appears, it's likely the same file moved.

    Args:
        waveform: Audio waveform as float32 numpy array (mono)
        sample_rate: Sample rate in Hz

    Returns:
        Base64-encoded chromaprint fingerprint string, or empty string on failure.

    """
    try:
        # Use first 60 seconds for fingerprinting (balance speed vs accuracy)
        max_samples = 60 * sample_rate
        audio_chunk = waveform[:max_samples] if len(waveform) > max_samples else waveform

        if len(audio_chunk) == 0:
            return ""

        # Convert float32 waveform to int16 PCM bytes for Chromaprint.
        # Scale to full int16 range, clip, and convert.
        scaled = np.clip(audio_chunk * 32767.0, -32768, 32767).astype(np.int16)
        pcm_bytes: bytes = scaled.tobytes()

        # Generate the fingerprint through pyacoustid's supported wrapper API.
        # The separately distributed ``chromaprint`` package does not expose
        # the Fingerprinter class used by older versions of this component.
        fingerprint = acoustid.fingerprint(sample_rate, 1, iter((pcm_bytes,)))
        return fingerprint.decode("utf-8") if isinstance(fingerprint, bytes) else str(fingerprint)

    except (ValueError, RuntimeError, acoustid.AcoustidError):
        logger.exception("[chromaprint] Failed to compute chromaprint")
        return ""
