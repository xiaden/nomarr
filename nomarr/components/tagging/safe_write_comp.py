"""Safe atomic file write component.

Implements copy-modify-verify-replace pattern to prevent file corruption
during tag writing. If a crash occurs during write, the original file
remains intact.

Two strategies:
1. Hardlink replacement (preferred): Uses temp folder, atomic hardlink swap
2. Fallback replacement: Uses .tmp file, delete+rename (modifies folder mtime)

Verification: After writing to the temp copy, audio properties (duration,
sample rate, channels) are probed using mutagen (header read only, no decode)
and compared against the original. This confirms the file is still a valid,
playable audio file with the same content shape.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import mutagen

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Temp folder name - ignored by music libraries and git
TEMP_FOLDER_NAME = ".ignore"

# Tolerance for duration comparison — allows for container rounding differences
DURATION_TOLERANCE_S = 1.0


@dataclass
class SafeWriteResult:
    """Result of a safe write operation."""

    success: bool
    error: str | None = None


@dataclass
class _AudioProperties:
    """Probed audio properties for sanity comparison."""

    duration: float
    sample_rate: int
    channels: int


def _probe_audio_properties(path: Path) -> _AudioProperties:
    """Probe audio file properties using mutagen (header read, no decode).

    Reads duration, sample rate, and channel count from the file's audio
    stream headers. Does not decode audio data.

    Raises:
        RuntimeError: If mutagen cannot parse the file.

    """
    audio = mutagen.File(str(path))
    if audio is None:
        msg = f"mutagen could not read audio file: {path.name}"
        raise RuntimeError(msg)
    info = audio.info
    return _AudioProperties(
        duration=float(info.length),
        sample_rate=int(info.sample_rate),
        channels=int(info.channels),
    )


def _check_audio_properties(original: _AudioProperties, after: _AudioProperties) -> str | None:
    """Return an error string if properties differ beyond tolerance, else None."""
    if abs(after.duration - original.duration) > DURATION_TOLERANCE_S:
        return (
            f"Duration changed: {original.duration:.2f}s \u2192 {after.duration:.2f}s "
            f"(tolerance \u00b1{DURATION_TOLERANCE_S}s)"
        )
    if after.sample_rate != original.sample_rate:
        return f"Sample rate changed: {original.sample_rate}Hz \u2192 {after.sample_rate}Hz"
    if after.channels != original.channels:
        return f"Channel count changed: {original.channels} \u2192 {after.channels}"
    return None


def _get_temp_folder(library_root: Path) -> Path:
    """Get or create the temp folder in library root."""
    temp_folder = library_root / TEMP_FOLDER_NAME
    temp_folder.mkdir(exist_ok=True)
    return temp_folder


def _supports_hardlinks(source: Path, temp_folder: Path) -> bool:
    """Check if filesystem supports hardlinks between source and temp folder."""
    test_file = temp_folder / f".hardlink_test_{uuid.uuid4().hex}"
    try:
        test_file.touch()
        test_link = source.parent / f".hardlink_test_{uuid.uuid4().hex}"
        try:
            os.link(test_file, test_link)
            test_link.unlink()
            return True
        except OSError:
            return False
        finally:
            if test_link.exists():
                test_link.unlink()
    except OSError:
        return False
    finally:
        if test_file.exists():
            test_file.unlink()


def safe_write_tags(
    library_path: LibraryPath,
    library_root: Path,
    write_fn: Callable[[Path], None],
) -> SafeWriteResult:
    """Safely write tags to an audio file using copy-modify-verify-replace.

    Args:
        library_path: The original file to modify
        library_root: Root path of the library (for temp folder location)
        write_fn: Function that writes tags to a Path (called on temp copy)

    Returns:
        SafeWriteResult with success status

    The write_fn receives a Path to the temp copy and should write tags to it.
    After write_fn completes, audio properties (duration, sample rate, channels)
    are probed from the temp copy and compared against the original to confirm
    the file is still a valid, playable audio file with the same content shape.
    The original is then atomically replaced.

    """
    if not library_path.is_valid():
        return SafeWriteResult(success=False, error=f"Invalid path: {library_path.reason}")

    original_path = library_path.absolute
    filename = original_path.name

    # Probe original before any writes
    try:
        original_props = _probe_audio_properties(original_path)
    except Exception as e:
        return SafeWriteResult(success=False, error=f"Failed to probe original file: {e}")

    # Try hardlink approach first
    temp_folder = _get_temp_folder(library_root)
    use_hardlink = _supports_hardlinks(original_path, temp_folder)

    if use_hardlink:
        return _safe_write_hardlink(original_path, temp_folder, filename, original_props, write_fn)
    return _safe_write_fallback(original_path, original_props, write_fn)


def _safe_write_hardlink(
    original_path: Path,
    temp_folder: Path,
    filename: str,
    original_props: _AudioProperties,
    write_fn: Callable[[Path], None],
) -> SafeWriteResult:
    """Safe write using hardlink replacement (atomic, no folder mtime change)."""
    temp_path = temp_folder / f"{uuid.uuid4().hex}_{filename}"

    try:
        # Step 1: Copy original to temp
        shutil.copy2(original_path, temp_path)
        logger.debug(f"[safe_write] Copied to temp: {temp_path}")

        # Step 2: Write tags to temp copy
        write_fn(temp_path)
        logger.debug("[safe_write] Wrote tags to temp copy")

        # Step 3: Verify audio properties unchanged
        after_props = _probe_audio_properties(temp_path)
        error = _check_audio_properties(original_props, after_props)
        if error:
            temp_path.unlink()
            return SafeWriteResult(success=False, error=f"Audio sanity check failed: {error}")
        logger.debug("[safe_write] Audio properties verified")

        # Step 4: Atomic hardlink replacement
        backup_path = original_path.with_suffix(original_path.suffix + ".bak")
        try:
            os.rename(original_path, backup_path)  # Atomic on same filesystem
            os.link(temp_path, original_path)
            backup_path.unlink()
            logger.debug("[safe_write] Hardlink replacement complete")
        except OSError as e:
            # Restore backup if hardlink failed
            if backup_path.exists() and not original_path.exists():
                os.rename(backup_path, original_path)
            msg = f"Hardlink replacement failed: {e}"
            raise RuntimeError(msg) from e

        return SafeWriteResult(success=True)

    except Exception as e:
        logger.exception(f"[safe_write] Hardlink write failed: {e}")
        return SafeWriteResult(success=False, error=str(e))

    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


def _safe_write_fallback(
    original_path: Path,
    original_props: _AudioProperties,
    write_fn: Callable[[Path], None],
) -> SafeWriteResult:
    """Safe write using .tmp file (modifies folder mtime)."""
    temp_path = original_path.with_suffix(original_path.suffix + ".tmp")

    try:
        # Step 1: Copy original to .tmp
        shutil.copy2(original_path, temp_path)
        logger.debug(f"[safe_write] Copied to .tmp: {temp_path}")

        # Step 2: Write tags to .tmp copy
        write_fn(temp_path)
        logger.debug("[safe_write] Wrote tags to .tmp copy")

        # Step 3: Verify audio properties unchanged
        after_props = _probe_audio_properties(temp_path)
        error = _check_audio_properties(original_props, after_props)
        if error:
            temp_path.unlink()
            return SafeWriteResult(success=False, error=f"Audio sanity check failed: {error}")
        logger.debug("[safe_write] Audio properties verified")

        # Step 4: Delete original, rename .tmp to original
        original_path.unlink()
        os.rename(temp_path, original_path)
        logger.debug("[safe_write] Fallback replacement complete")

        return SafeWriteResult(success=True)

    except Exception as e:
        logger.exception(f"[safe_write] Fallback write failed: {e}")
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()
        return SafeWriteResult(success=False, error=str(e))
