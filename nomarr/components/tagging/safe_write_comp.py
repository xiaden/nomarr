"""Safe atomic file write component.

Implements copy-modify-verify-replace pattern to prevent file corruption
during tag writing. If a crash occurs during write, the original file
remains intact.

Two strategies:
1. Hardlink replacement (preferred): Uses temp folder, atomic hardlink swap
2. Fallback replacement: Uses .tmp file, delete+rename (modifies folder mtime)
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Temp folder name - ignored by music libraries and git
TEMP_FOLDER_NAME = ".ignore"


@dataclass
class SafeWriteResult:
    """Result of a safe write operation."""

    success: bool
    error: str | None = None


def _get_temp_folder(library_root: Path) -> Path:
    """Get or create the temp folder in library root."""
    temp_folder = library_root / TEMP_FOLDER_NAME
    temp_folder.mkdir(exist_ok=True)
    return temp_folder


def _supports_hardlinks(source: Path, temp_folder: Path) -> bool:
    """Check if filesystem supports hardlinks between source and temp folder."""
    test_file = temp_folder / f".hardlink_test_{uuid.uuid4().hex}"
    try:
        # Create a test file and try to hardlink it
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


def _compute_chromaprint_for_path(path: Path) -> str:
    """Compute chromaprint for a file path (not LibraryPath)."""
    # Import here to avoid circular imports and heavy deps at module load
    from nomarr.components.ml.chromaprint_comp import compute_chromaprint
    from nomarr.components.ml.ml_audio_comp import load_audio_mono

    result = load_audio_mono(str(path), target_sr=16000)
    return compute_chromaprint(result.waveform, result.sample_rate)


def safe_write_tags(
    library_path: LibraryPath,
    library_root: Path,
    original_chromaprint: str,
    write_fn: Callable[[Path], None],
) -> SafeWriteResult:
    """
    Safely write tags to an audio file using copy-modify-verify-replace.

    Args:
        library_path: The original file to modify
        library_root: Root path of the library (for temp folder location)
        original_chromaprint: Chromaprint of original file (for verification)
        write_fn: Function that writes tags to a Path (called on temp copy)

    Returns:
        SafeWriteResult with success status

    The write_fn receives a Path to the temp copy and should write tags to it.
    After write_fn completes, we verify the audio content hasn't changed by
    comparing chromaprints, then atomically replace the original.
    """
    if not library_path.is_valid():
        return SafeWriteResult(
            success=False,
            error=f"Invalid path: {library_path.reason}",
        )

    original_path = library_path.absolute
    filename = original_path.name

    # Try hardlink approach first
    temp_folder = _get_temp_folder(library_root)
    use_hardlink = _supports_hardlinks(original_path, temp_folder)

    if use_hardlink:
        return _safe_write_hardlink(original_path, temp_folder, filename, original_chromaprint, write_fn)
    else:
        return _safe_write_fallback(original_path, original_chromaprint, write_fn)


def _safe_write_hardlink(
    original_path: Path,
    temp_folder: Path,
    filename: str,
    original_chromaprint: str,
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

        # Step 3: Verify chromaprint matches
        new_chromaprint = _compute_chromaprint_for_path(temp_path)
        if new_chromaprint != original_chromaprint:
            temp_path.unlink()
            return SafeWriteResult(
                success=False,
                error=f"Audio content changed during tag write! Original: {original_chromaprint[:16]}..., "
                f"After: {new_chromaprint[:16]}...",
            )
        logger.debug("[safe_write] Chromaprint verified")

        # Step 4: Atomic hardlink replacement
        # Remove original, hardlink temp to original location
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
            raise RuntimeError(f"Hardlink replacement failed: {e}") from e

        return SafeWriteResult(success=True)

    except Exception as e:
        logger.error(f"[safe_write] Hardlink write failed: {e}")
        return SafeWriteResult(success=False, error=str(e))

    finally:
        # Clean up temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _safe_write_fallback(
    original_path: Path,
    original_chromaprint: str,
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

        # Step 3: Verify chromaprint matches
        new_chromaprint = _compute_chromaprint_for_path(temp_path)
        if new_chromaprint != original_chromaprint:
            temp_path.unlink()
            return SafeWriteResult(
                success=False,
                error=f"Audio content changed during tag write! Original: {original_chromaprint[:16]}..., "
                f"After: {new_chromaprint[:16]}...",
            )
        logger.debug("[safe_write] Chromaprint verified")

        # Step 4: Delete original, rename .tmp to original
        original_path.unlink()
        os.rename(temp_path, original_path)
        logger.debug("[safe_write] Fallback replacement complete")

        return SafeWriteResult(success=True)

    except Exception as e:
        logger.error(f"[safe_write] Fallback write failed: {e}")
        # Clean up temp file on failure
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        return SafeWriteResult(success=False, error=str(e))
