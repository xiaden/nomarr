"""Tests for ``nomarr.components.ml.audio.ml_chromaprint_comp``."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from nomarr.components.ml.audio.ml_chromaprint_comp import compute_chromaprint

SAMPLE_RATE = 16_000


def _sine_wave(duration_seconds: float, frequency: float = 440.0) -> np.ndarray:
    """Generate a synthetic mono sine wave as float32."""
    n_samples = int(SAMPLE_RATE * duration_seconds)
    t = np.arange(n_samples, dtype=np.float32) / SAMPLE_RATE
    wave: np.ndarray = np.sin(2.0 * np.pi * frequency * t, dtype=np.float32)  # type: ignore[no-any-return]
    return wave


@pytest.mark.unit
class TestComputeChromaprint:
    """Tests for ``compute_chromaprint``."""

    def test_compute_chromaprint_returns_nonempty_string(self) -> None:
        """A 5-second 440 Hz sine wave should produce a non-empty fingerprint."""
        waveform = _sine_wave(duration_seconds=5.0)
        result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compute_chromaprint_deterministic(self) -> None:
        """Identical input should always produce the same fingerprint."""
        waveform = _sine_wave(duration_seconds=5.0)
        result_a = compute_chromaprint(waveform, SAMPLE_RATE)
        result_b = compute_chromaprint(waveform, SAMPLE_RATE)
        assert result_a == result_b

    def test_compute_chromaprint_different_audio_different_fingerprint(self) -> None:
        """Two different waveforms should produce different fingerprints."""
        wave_a = _sine_wave(duration_seconds=5.0, frequency=200.0)
        wave_b = _sine_wave(duration_seconds=5.0, frequency=3000.0)
        fp_a = compute_chromaprint(wave_a, SAMPLE_RATE)
        fp_b = compute_chromaprint(wave_b, SAMPLE_RATE)
        assert fp_a != fp_b

    def test_compute_chromaprint_short_audio(self) -> None:
        """Very short audio (< 1 second) should not crash."""
        waveform = _sine_wave(duration_seconds=0.1)
        result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert isinstance(result, str)

    def test_compute_chromaprint_silence(self) -> None:
        """All-zeros waveform should return a string (not raise)."""
        waveform = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)  # 2 seconds silence
        result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert isinstance(result, str)

    def test_compute_chromaprint_empty_waveform(self) -> None:
        """Zero-length waveform should return a string via the exception fallback."""
        waveform = np.array([], dtype=np.float32)
        result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert isinstance(result, str)

    def test_compute_chromaprint_long_audio_truncated(self) -> None:
        """Audio longer than 60 seconds should be handled without error or hang."""
        waveform = _sine_wave(duration_seconds=90.0)
        result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.mocked
    def test_compute_chromaprint_fallback_on_error(self) -> None:
        """When Chromaprint library raises, the function should return an empty string."""
        waveform = _sine_wave(duration_seconds=5.0)
        with patch(
            "nomarr.components.ml.audio.ml_chromaprint_comp.acoustid.fingerprint",
            side_effect=RuntimeError("simulated Chromaprint failure"),
        ):
            result = compute_chromaprint(waveform, SAMPLE_RATE)
        assert result == ""
