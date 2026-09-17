"""Safe atomic file write component.

Implements copy-modify-verify-replace pattern to prevent file corruption
during tag writing. If a crash occurs during write, the original file
remains intact.

Two strategies:
1. Hardlink replacement (preferred): Uses temp folder, atomic backup-link swap
2. Fallback replacement: Uses a same-directory temp file + os.replace (modifies folder mtime)

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
from mutagen import MutagenError
from mutagen.oggopus import OggOpusInfo

from nomarr.helpers.fs_contract import FsFact, fact_from_error

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from nomarr.helpers.dto.library_dto import WriteOutcome
    from nomarr.helpers.dto.path_dto import LibraryPath

logger = logging.getLogger(__name__)

# Temp folder name - ignored by music libraries and git
TEMP_FOLDER_NAME = ".ignore"

# Tolerance for duration comparison — allows for container rounding differences
DURATION_TOLERANCE_S = 1.0

# Opus decodes to a fixed 48 kHz output rate regardless of the container's original
# sample rate; mutagen's ``OggOpusInfo._post_tags`` derives ``length`` as
# ``(page.position - pre_skip) / 48000.0`` and discards ``orig_sample_rate``, so this
# constant is the true decoder output rate (RFC 7845 §5.1).
OPUS_DECODED_SAMPLE_RATE_HZ = 48000


@dataclass
class SafeWriteResult:
    """Result of a safe write operation."""

    success: bool
    new_mtime_ms: int | None = None
    fs_fact: FsFact | None = None
    outcome: WriteOutcome | None = None

    @property
    def error(self) -> str | None:
        """Derived, read-only ``str | None`` view over the structured fields (DD §10.2).

        ``error`` is not an independently settable field: it is a pure function of
        ``success``/``outcome``/``fs_fact``, so no duplicate truth channel can drift.
        ``outcome == "modified_externally"`` renders the legacy ``"file_modified_externally"``
        token for backward-compatible textual reporting and logging; every other outcome
        maps to its own name.
        """
        if self.success:
            return None
        if self.outcome == "modified_externally":
            return "file_modified_externally"
        if self.outcome is not None:
            return self.outcome
        if self.fs_fact is not None:
            return self.fs_fact.kind
        return None


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
    sample_rate = getattr(info, "sample_rate", None)
    if sample_rate is None:
        if not isinstance(info, OggOpusInfo):
            msg = f"audio info of type {type(info).__name__} exposes no sample_rate"
            raise RuntimeError(msg)
        sample_rate = OPUS_DECODED_SAMPLE_RATE_HZ
    return _AudioProperties(
        duration=float(info.length),
        sample_rate=int(sample_rate),
        channels=int(info.channels),
    )


def _check_audio_properties(original: _AudioProperties, after: _AudioProperties) -> bool:
    """Return ``True`` when properties differ beyond tolerance, else ``False``."""
    return (
        abs(after.duration - original.duration) > DURATION_TOLERANCE_S
        or after.sample_rate != original.sample_rate
        or after.channels != original.channels
    )


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
    expected_mtime_ms: int,
) -> SafeWriteResult:
    """Safely write tags to an audio file using copy-modify-verify-replace.

    Args:
        library_path: The original file to modify
        library_root: Root path of the library (for temp folder location)
        write_fn: Function that writes tags to a Path (called on temp copy)
        expected_mtime_ms: Modification time of the original file in milliseconds
            when the caller last read it.  If the actual mtime has changed the
            write is aborted to avoid overwriting external modifications.

    Returns:
        SafeWriteResult with success status

    The write_fn receives a Path to the temp copy and should write tags to it.
    After write_fn completes, audio properties (duration, sample rate, channels)
    are probed from the temp copy and compared against the original to confirm
    the file is still a valid, playable audio file with the same content shape.
    The original is then atomically replaced.

    """
    if not library_path.is_valid():
        if library_path.library_id is None:
            return SafeWriteResult(success=False, outcome="library_unresolved")
        return SafeWriteResult(
            success=False,
            fs_fact=FsFact(presence="unknown", kind="invalid_path", errno=None),
        )

    original_path = library_path.absolute
    filename = original_path.name

    # Pre-flight: abort if file was modified externally since caller read it
    try:
        actual_mtime_ms = int(os.stat(original_path).st_mtime * 1000)
    except OSError as exc:
        logger.exception(f"[tagging] Failed to stat original file: {exc}")
        return SafeWriteResult(
            success=False,
            fs_fact=fact_from_error(exc, path=str(original_path)),
        )
    if actual_mtime_ms != expected_mtime_ms:
        return SafeWriteResult(success=False, new_mtime_ms=None, outcome="modified_externally")

    # Probe original before any writes
    try:
        original_props = _probe_audio_properties(original_path)
    except OSError:
        return SafeWriteResult(success=False, outcome="probe_failed_transient")
    except (RuntimeError, MutagenError):
        return SafeWriteResult(success=False, outcome="probe_unsupported")

    # Try hardlink approach first
    try:
        temp_folder = _get_temp_folder(library_root)
    except OSError as exc:
        logger.exception(f"[tagging] Failed to prepare temp folder: {exc}")
        return SafeWriteResult(
            success=False,
            fs_fact=fact_from_error(exc, path=str(library_root / TEMP_FOLDER_NAME)),
        )
    use_hardlink = _supports_hardlinks(original_path, temp_folder)

    if use_hardlink:
        return _safe_write_hardlink(original_path, temp_folder, filename, original_props, write_fn, expected_mtime_ms)
    return _safe_write_fallback(original_path, original_props, write_fn, expected_mtime_ms)


def _safe_write_hardlink(
    original_path: Path,
    temp_folder: Path,
    filename: str,
    original_props: _AudioProperties,
    write_fn: Callable[[Path], None],
    _expected_mtime_ms: int,
) -> SafeWriteResult:
    """Safe write using the atomic hardlink backup-link swap."""
    temp_path = temp_folder / f"{uuid.uuid4().hex}_{filename}"

    try:
        # Step 1: Copy original to temp
        shutil.copy2(original_path, temp_path)
        logger.debug(f"[tagging] Copied to temp: {temp_path}")

        # Step 2: Write tags to temp copy
        write_fn(temp_path)
        logger.debug("[tagging] Wrote tags to temp copy")

        # Step 3: Verify audio properties unchanged
        after_props = _probe_audio_properties(temp_path)
        if _check_audio_properties(original_props, after_props):
            return SafeWriteResult(success=False, outcome="audio_sanity_failed")
        logger.debug("[tagging] Audio properties verified")

        # Step 4: Atomic backup-link swap. Create a namespaced, non-audio backup hardlink
        # first so the original is never absent, then swap in the new content atomically,
        # then best-effort remove only this call's backup.
        backup_path = original_path.parent / f".{original_path.name}.{uuid.uuid4().hex}.nomarr-bak"
        try:
            os.link(original_path, backup_path)
        except OSError as exc:
            return SafeWriteResult(
                success=False,
                fs_fact=fact_from_error(exc, path=str(original_path)),
            )

        # os.link proves the original existed. Confirm nothing removed it meanwhile; if
        # it vanished, abort and preserve the backup (never restore/delete a `.bak`).
        if not original_path.exists():
            return SafeWriteResult(success=False, outcome="write_failed")

        try:
            os.replace(temp_path, original_path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                backup_path.unlink()
            return SafeWriteResult(
                success=False,
                fs_fact=fact_from_error(exc, path=str(original_path)),
            )
        logger.debug("[tagging] Hardlink replacement complete")

        advisory_fact: FsFact | None = None
        try:
            backup_path.unlink()
        except OSError as exc:
            # The write already succeeded; the backup cleanup failure is advisory only.
            advisory_fact = fact_from_error(exc, path=str(backup_path))

        try:
            new_mtime_ms = int(os.stat(original_path).st_mtime * 1000)
        except OSError as exc:
            # The write already succeeded; the mtime read failure is advisory only.
            if advisory_fact is None:
                advisory_fact = fact_from_error(exc, path=str(original_path))
            new_mtime_ms = None

        return SafeWriteResult(success=True, new_mtime_ms=new_mtime_ms, fs_fact=advisory_fact)

    except OSError as exc:
        logger.exception(f"[tagging] Hardlink write failed: {exc}")
        return SafeWriteResult(
            success=False,
            outcome="write_failed",
            fs_fact=fact_from_error(exc, path=str(original_path)),
        )
    except Exception as exc:
        logger.exception(f"[tagging] Hardlink write failed: {exc}")
        return SafeWriteResult(success=False, outcome="write_failed")

    finally:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()


def _safe_write_fallback(
    original_path: Path,
    original_props: _AudioProperties,
    write_fn: Callable[[Path], None],
    _expected_mtime_ms: int,
) -> SafeWriteResult:
    """Safe write using a same-directory temp file + atomic ``os.replace``."""
    temp_path = original_path.parent / f".{original_path.name}.{uuid.uuid4().hex}.nomarr-tmp"

    try:
        # Step 1: Copy original to the same-directory temp
        shutil.copy2(original_path, temp_path)
        logger.debug(f"[tagging] Copied to temp: {temp_path}")

        # Step 2: Write tags to the temp copy
        write_fn(temp_path)
        logger.debug("[tagging] Wrote tags to temp copy")

        # Step 3: Verify audio properties unchanged
        after_props = _probe_audio_properties(temp_path)
        if _check_audio_properties(original_props, after_props):
            return SafeWriteResult(success=False, outcome="audio_sanity_failed")
        logger.debug("[tagging] Audio properties verified")

        # Step 4: Atomic same-directory replace (no unlink-before-rename window)
        os.replace(temp_path, original_path)
        logger.debug("[tagging] Fallback replacement complete")

        try:
            new_mtime_ms = int(os.stat(original_path).st_mtime * 1000)
        except OSError as exc:
            # The write already succeeded; the mtime read failure is advisory only.
            return SafeWriteResult(
                success=True,
                new_mtime_ms=None,
                fs_fact=fact_from_error(exc, path=str(original_path)),
            )
        return SafeWriteResult(success=True, new_mtime_ms=new_mtime_ms)

    except OSError as exc:
        logger.exception(f"[tagging] Fallback write failed: {exc}")
        return SafeWriteResult(
            success=False,
            outcome="write_failed",
            fs_fact=fact_from_error(exc, path=str(original_path)),
        )
    except Exception as exc:
        logger.exception(f"[tagging] Fallback write failed: {exc}")
        return SafeWriteResult(success=False, outcome="write_failed")

    finally:
        with contextlib.suppress(OSError):
            if temp_path.exists():
                temp_path.unlink()
