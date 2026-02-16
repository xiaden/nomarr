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


def _write_all(fd: int, data: bytes) -> None:
    """Write all bytes to a file descriptor."""
    mv = memoryview(data)
    while mv:
        n = os.write(fd, mv)
        mv = mv[n:]


def _child_audio_loop(req_fd: int, resp_fd: int) -> None:
    """Child process main loop: read file paths, load audio, write responses.

    Protocol per request:
        Parent → Child: [path_len:4][target_sr:4][path_bytes:path_len]
        Child → Parent: [0x01][n_samples:4][audio_bytes] on success
                        [0x00] on error (essentia exception, not crash)

    If MonoLoader causes SIGSEGV, this process dies.
    Parent detects via broken pipe (EOF) and respawns.
    """
    try:
        while True:
            # Read request header: [path_len:4][target_sr:4]
            header = b""
            while len(header) < 8:
                chunk = os.read(req_fd, 8 - len(header))
                if not chunk:
                    return  # Parent closed pipe → exit cleanly
                header += chunk

            path_len, target_sr = struct.unpack("<II", header)

            # Read path bytes
            path_bytes = b""
            while len(path_bytes) < path_len:
                chunk = os.read(req_fd, path_len - len(path_bytes))
                if not chunk:
                    return
                path_bytes += chunk
            path_str = path_bytes.decode("utf-8")

            try:
                audio = MonoLoader(filename=path_str, sampleRate=target_sr, resampleQuality=4)()
                # Success: [0x01][n_samples:4][audio_bytes]
                resp = b"\x01" + struct.pack("<I", len(audio)) + audio.tobytes()
                _write_all(resp_fd, resp)
            except Exception:
                # Caught exception (not crash) → report error, stay alive
                _write_all(resp_fd, b"\x00")
    except Exception:
        pass  # Uncaught error → exit silently


class _PersistentAudioLoader:
    """Persistent subprocess for crash-isolated audio loading.

    Maintains a long-running child process that receives file paths via pipe
    and returns decoded audio. Only respawns when the child crashes (SIGSEGV).

    Compared to fork-per-file (~200-500ms overhead each), this adds near-zero
    IPC overhead per load after the initial spawn.
    """

    def __init__(self) -> None:
        self._child_pid: int | None = None
        self._to_child: int | None = None
        self._from_child: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _spawn(self) -> None:
        """Fork a persistent child process."""
        req_r, req_w = os.pipe()  # type: ignore[attr-defined]
        resp_r, resp_w = os.pipe()  # type: ignore[attr-defined]

        pid = os.fork()  # type: ignore[attr-defined]
        if pid == 0:
            # === CHILD ===
            os.close(req_w)
            os.close(resp_r)
            _child_audio_loop(req_r, resp_w)
            os._exit(0)  # type: ignore[attr-defined]

        # === PARENT ===
        os.close(req_r)
        os.close(resp_w)
        self._child_pid = pid
        self._to_child = req_w
        self._from_child = resp_r

    def _ensure_alive(self) -> None:
        """Spawn child if not running."""
        if self._child_pid is None:
            self._spawn()

    def _kill_child(self) -> None:
        """Kill and reap the child process, close pipes."""
        if self._child_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(self._child_pid, signal.SIGKILL)  # type: ignore[attr-defined]
            with contextlib.suppress(ChildProcessError):
                _reap_child(self._child_pid)
            self._child_pid = None
        for attr in ("_to_child", "_from_child"):
            fd: int | None = getattr(self, attr)
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
                setattr(self, attr, None)

    def _cleanup_dead_child(self) -> None:
        """Clean up a child that already exited (no SIGKILL)."""
        if self._child_pid is not None:
            with contextlib.suppress(ChildProcessError):
                _reap_child(self._child_pid)
            self._child_pid = None
        for attr in ("_to_child", "_from_child"):
            fd_val: int | None = getattr(self, attr)
            if fd_val is not None:
                with contextlib.suppress(OSError):
                    os.close(fd_val)
                setattr(self, attr, None)

    def shutdown(self) -> None:
        """Stop the child process."""
        self._kill_child()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self, path_str: str, target_sr: int, timeout: float = 120.0) -> np.ndarray:
        """Load audio via persistent child with single retry on crash.

        Args:
            path_str: Absolute file path
            target_sr: Target sample rate
            timeout: Timeout per attempt in seconds

        Returns:
            Audio waveform as float32 numpy array

        Raises:
            AudioLoadCrashError: If both attempts fail
            AudioLoadShutdownError: If shutdown requested during load
        """
        for attempt in range(2):
            if _stop_event is not None and _stop_event.is_set():
                raise AudioLoadShutdownError("Shutdown requested before audio load")

            self._ensure_alive()
            audio = self._try_load_one(path_str, target_sr, attempt, timeout)
            if audio is not None:
                return audio

        raise AudioLoadCrashError(f"Audio load failed twice: {path_str}")

    def _try_load_one(
        self, path_str: str, target_sr: int, attempt: int, timeout: float
    ) -> np.ndarray | None:
        """Single load attempt. Returns audio or None on failure."""
        # Send request: [path_len:4][target_sr:4][path_bytes]
        path_bytes = path_str.encode("utf-8")
        request = struct.pack("<II", len(path_bytes), target_sr) + path_bytes
        try:
            os.write(self._to_child, request)  # type: ignore[arg-type]
        except OSError:
            self._cleanup_dead_child()
            logger.warning(
                "[audio] Child dead before send for %s (attempt %d)",
                path_str,
                attempt + 1,
            )
            return None

        return self._read_response(path_str, attempt, timeout)

    def _read_response(
        self, path_str: str, attempt: int, timeout: float
    ) -> np.ndarray | None:
        """Read one response from child with shutdown-aware polling."""
        buf = bytearray()
        deadline_ms = internal_ms().value + int(timeout * 1000)
        expected_total: int | None = None

        while True:
            # Shutdown check
            if _stop_event is not None and _stop_event.is_set():
                self._kill_child()
                raise AudioLoadShutdownError("Shutdown during audio load")

            # Timeout check
            remaining_s = (deadline_ms - internal_ms().value) / 1000
            if remaining_s <= 0:
                self._kill_child()
                logger.warning(
                    "[audio] Load timed out for %s (attempt %d)",
                    path_str,
                    attempt + 1,
                )
                return None

            # Poll pipe (250ms intervals for responsive shutdown)
            ready, _, _ = select.select(
                [self._from_child], [], [], min(0.25, remaining_s)
            )
            if not ready:
                continue

            chunk = os.read(self._from_child, 65536)  # type: ignore[arg-type]
            if not chunk:
                # EOF → child crashed (SIGSEGV or unexpected exit)
                self._cleanup_dead_child()
                logger.warning(
                    "[audio] Child crashed for %s (attempt %d)",
                    path_str,
                    attempt + 1,
                )
                return None
            buf.extend(chunk)

            # Parse response once we have enough bytes
            if len(buf) < 1:
                continue

            status = buf[0]
            if status == 0x00:
                # Essentia exception (not crash) — child is still alive
                logger.warning(
                    "[audio] Load error for %s (attempt %d)",
                    path_str,
                    attempt + 1,
                )
                return None

            # status == 0x01: success — need [1 + 4 + n_samples*4] bytes total
            if expected_total is None and len(buf) >= 5:
                (n_samples,) = struct.unpack("<I", buf[1:5])
                expected_total = 5 + n_samples * 4

            if expected_total is not None and len(buf) >= expected_total:
                return np.frombuffer(bytes(buf[5:expected_total]), dtype=np.float32)


# Module-level persistent audio loader (lazily initialised).
_loader: _PersistentAudioLoader | None = None


def _get_loader() -> _PersistentAudioLoader:
    """Get or create the persistent audio loader."""
    global _loader
    if _loader is None:
        _loader = _PersistentAudioLoader()
    return _loader


def shutdown_audio_loader() -> None:
    """Shut down the persistent audio loader subprocess.

    Safe to call multiple times or when no loader has been created.
    Called by the worker during cleanup.
    """
    global _loader
    if _loader is not None:
        _loader.shutdown()
        _loader = None


def _load_with_retry(path_str: str, target_sr: int, timeout: float = 120.0) -> np.ndarray:
    """Load audio via persistent subprocess with single retry on crash.

    Uses a long-running child process that receives file paths over a pipe
    and returns decoded audio.  If the child crashes (SIGSEGV from corrupt
    files), it is respawned and the load is retried once.

    Args:
        path_str: File path
        target_sr: Target sample rate
        timeout: Timeout per attempt in seconds

    Returns:
        Audio waveform as float32 numpy array

    Raises:
        AudioLoadCrashError: If both load attempts fail
        AudioLoadShutdownError: If shutdown requested during load
    """
    return _get_loader().load(path_str, target_sr, timeout)


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
