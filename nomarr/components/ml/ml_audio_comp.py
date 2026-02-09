"""Audio validation and loading for ML processing."""

from __future__ import annotations

import contextlib
import logging
import os
import select
import signal
import struct
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy.signal import resample_poly

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia
from nomarr.helpers.dto.ml_dto import LoadAudioMonoResult
from nomarr.helpers.time_helper import internal_ms

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Use Essentia for audio loading (supports more formats via ffmpeg)
HAVE_ESSENTIA = backend_essentia.is_available()

if HAVE_ESSENTIA:
    MonoLoader = backend_essentia.essentia_tf.MonoLoader
else:
    # Fallback to soundfile if Essentia not available
    import soundfile as sf

    MonoLoader = None


class AudioLoadCrashError(Exception):
    """Audio load crashed twice - file should be marked invalid."""


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


def _reap_child(pid: int) -> int:
    """Wait for child and return exit code (negative = signal). Unix-only."""
    _, status = os.waitpid(pid, 0)  # type: ignore[attr-defined]  # Unix-only
    if os.WIFEXITED(status):  # type: ignore[attr-defined]
        return int(os.WEXITSTATUS(status))  # type: ignore[attr-defined]
    if os.WIFSIGNALED(status):  # type: ignore[attr-defined]
        return -int(os.WTERMSIG(status))  # type: ignore[attr-defined]
    return -999


def _load_with_retry(path_str: str, target_sr: int, timeout: float = 120.0) -> np.ndarray:
    """Load audio via fork-isolated subprocess with single retry.

    Forks a child that inherits the already-loaded MonoLoader binding.
    The child loads audio and pipes raw float32 bytes back. If essentia
    crashes (SIGSEGV on corrupt files), only the child dies.

    The parent polls with 250ms select() intervals, checking the worker's
    stop event between polls for responsive shutdown.

    Args:
        path_str: File path
        target_sr: Target sample rate
        timeout: Timeout per attempt in seconds

    Returns:
        Audio waveform as float32 numpy array

    Raises:
        AudioLoadCrashError: If both load attempts crash
        AudioLoadShutdownError: If shutdown requested during load

    """
    for attempt in range(2):
        if _stop_event is not None and _stop_event.is_set():
            raise AudioLoadShutdownError("Shutdown requested before audio load")

        r_fd, w_fd = os.pipe()  # type: ignore[attr-defined]  # Unix-only
        child_pid = os.fork()  # type: ignore[attr-defined]

        if child_pid == 0:
            # === CHILD: load audio, write to pipe, exit ===
            os.close(r_fd)
            try:
                audio = MonoLoader(filename=path_str, sampleRate=target_sr, resampleQuality=4)()
                with os.fdopen(w_fd, "wb", buffering=0) as wf:
                    wf.write(struct.pack("<I", len(audio)))
                    wf.write(audio.tobytes())
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(w_fd)
            os._exit(0)  # type: ignore[attr-defined]

        # === PARENT: read pipe with shutdown-aware polling ===
        os.close(w_fd)
        buf = bytearray()
        deadline_ms = internal_ms().value + int(timeout * 1000)
        eof = False

        try:
            while not eof:
                # Shutdown check
                if _stop_event is not None and _stop_event.is_set():
                    os.kill(child_pid, signal.SIGKILL)  # type: ignore[attr-defined]
                    _reap_child(child_pid)
                    raise AudioLoadShutdownError("Shutdown during audio load")

                # Timeout check
                remaining_s = (deadline_ms - internal_ms().value) / 1000
                if remaining_s <= 0:
                    os.kill(child_pid, signal.SIGKILL)  # type: ignore[attr-defined]
                    _reap_child(child_pid)
                    logger.warning("[audio] Load timed out for %s (attempt %d)", path_str, attempt + 1)
                    break

                # Poll pipe (250ms intervals for responsive shutdown)
                ready, _, _ = select.select([r_fd], [], [], min(0.25, remaining_s))
                if ready:
                    chunk = os.read(r_fd, 65536)
                    if not chunk:
                        eof = True
                    else:
                        buf.extend(chunk)

            if not eof:
                continue  # Timed out, retry

        except AudioLoadShutdownError:
            os.close(r_fd)
            raise
        except Exception:
            # Unexpected error - cleanup
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)  # type: ignore[attr-defined]
            _reap_child(child_pid)
            os.close(r_fd)
            raise

        os.close(r_fd)

        # Reap child and check exit status
        exitcode = _reap_child(child_pid)
        if exitcode != 0:
            logger.warning(
                "[audio] Load crashed (exit=%d) for %s (attempt %d)",
                exitcode,
                path_str,
                attempt + 1,
            )
            continue

        # Parse audio from pipe buffer
        if len(buf) < 4:
            logger.warning("[audio] Empty output for %s (attempt %d)", path_str, attempt + 1)
            continue
        (n_samples,) = struct.unpack("<I", buf[:4])
        audio = np.frombuffer(bytes(buf[4:]), dtype=np.float32)
        if len(audio) != n_samples:
            logger.warning(
                "[audio] Sample count mismatch (%d vs %d) for %s (attempt %d)",
                len(audio),
                n_samples,
                path_str,
                attempt + 1,
            )
            continue
        return audio

    # Both attempts failed
    raise AudioLoadCrashError(f"Audio load crashed twice: {path_str}")


def load_audio_mono(path: LibraryPath | str, target_sr: int = 16000) -> LoadAudioMonoResult:
    """Load an audio file as mono float32 in [-1, 1] at target_sr.
    Returns: LoadAudioMonoResult with waveform, sample_rate, duration.

    Uses Essentia's MonoLoader for broad format support (M4A, MP3, FLAC, etc.).
    Falls back to soundfile if Essentia is not available.

    Args:
        path: LibraryPath (validated) or str (absolute path, validation bypassed)
        target_sr: Target sample rate in Hz

    Raises:
        ValueError: If LibraryPath is invalid

    """
    # Handle both LibraryPath and str
    if isinstance(path, str):
        path_str = path
    else:
        # Enforce validation before file operations for LibraryPath
        if not path.is_valid():
            msg = f"Cannot load audio from invalid path ({path.status}): {path.absolute} - {path.reason}"
            raise ValueError(msg)
        path_str = str(path.absolute)

    if HAVE_ESSENTIA:
        # Crash-safe load via subprocess isolation (essentia can SIGSEGV on corrupt files)
        audio = _load_with_retry(path_str, target_sr)
        sr = int(target_sr)
        duration = float(len(audio)) / float(sr) if sr > 0 else 0.0
        return LoadAudioMonoResult(waveform=audio, sample_rate=sr, duration=duration)
    # Fallback to soundfile (limited format support)
    audio, sr = sf.read(path, always_2d=False)
    # Convert to mono
    if hasattr(audio, "ndim") and audio.ndim == 2:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)

    # Resample if needed (polyphase is robust + fast)
    if sr != target_sr:
        # gcd for rational factor
        gcd = np.gcd(int(sr), int(target_sr))
        up, down = int(target_sr) // gcd, int(sr) // gcd
        audio = resample_poly(audio, up, down).astype(np.float32, copy=False)
        sr = int(target_sr)

    duration = float(len(audio)) / float(sr) if sr > 0 else 0.0
    return LoadAudioMonoResult(waveform=audio, sample_rate=sr, duration=duration)


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
