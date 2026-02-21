"""Audio validation and loading for ML processing."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import essentia  # noqa: F401  # imported for __version__ access
import essentia.standard as _estd
import numpy as np

from nomarr.helpers.dto.ml_dto import LoadAudioMonoResult

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

# Essentia: minimal build (AudioLoader+MonoLoader+MonoMixer+Resample, no TF).
# AudioLoader has crash-hardening patches. Built from build_resources/essentia/.

logger = logging.getLogger(__name__)


class AudioLoadCrashError(Exception):
    """Audio file could not be decoded — file should be marked invalid."""


class AudioLoadShutdownError(Exception):
    """Audio load aborted due to worker shutdown."""


# Module-level stop event for shutdown-aware audio loading.
# Set by the worker at startup via set_stop_event().
_stop_event: Any = None


def set_stop_event(event: Any) -> None:
    """Register a stop event for shutdown-aware audio loading.

    The event must support `.is_set() -> bool`. Typically a
    multiprocessing.Event shared with the worker's parent process.
    """
    global _stop_event
    _stop_event = event


def shutdown_audio_loader() -> None:
    """No-op — retained for API compatibility.

    Essentia (no-TF build) has no persistent subprocess to stop.
    """


def load_audio_mono(path: LibraryPath | str, target_sr: int = 16000) -> LoadAudioMonoResult:
    """Load an audio file as mono float32 in [-1, 1] at target_sr.

    Uses essentia.standard.MonoLoader — backed by ffmpeg, handles MP3, M4A/AAC,
    FLAC, OGG, WAV, and anything else ffmpeg can decode. Resampling is done
    internally by MonoLoader via libsamplerate (resampleQuality=4).

    Args:
        path: LibraryPath (validated) or str (absolute path, validation bypassed).
        target_sr: Target sample rate in Hz.

    Returns:
        LoadAudioMonoResult with waveform, sample_rate, duration.

    Raises:
        ValueError: If LibraryPath is invalid.
        AudioLoadShutdownError: If shutdown was requested before loading.
        AudioLoadCrashError: If the file cannot be decoded.
    """
    if isinstance(path, str):
        path_str = path
    else:
        if not path.is_valid():
            msg = (
                f"Cannot load audio from invalid path ({path.status}): "
                f"{path.absolute} - {path.reason}"
            )
            raise ValueError(msg)
        path_str = str(path.absolute)

    if _stop_event is not None and _stop_event.is_set():
        raise AudioLoadShutdownError("Shutdown requested before audio load")

    try:
        audio: np.ndarray = _estd.MonoLoader(
            filename=path_str,
            sampleRate=target_sr,
            resampleQuality=4,
        )()
        sr = int(target_sr)
        duration = float(len(audio)) / float(sr) if sr > 0 else 0.0
        return LoadAudioMonoResult(waveform=audio, sample_rate=sr, duration=duration)

    except (AudioLoadShutdownError, ValueError):
        raise
    except Exception as exc:
        raise AudioLoadCrashError(f"Failed to decode audio: {path_str}") from exc


def should_skip_short(duration_s: float, min_duration_s: int, allow_short: bool) -> bool:
    """Check if audio file should be skipped due to insufficient duration.

    Args:
        duration_s: Audio duration in seconds
        min_duration_s: Minimum required duration in seconds
        allow_short: If True, allow short files regardless of duration

    Returns:
        True if file should be skipped, False otherwise

    """
    if allow_short:
        return False
    return duration_s < float(min_duration_s)
