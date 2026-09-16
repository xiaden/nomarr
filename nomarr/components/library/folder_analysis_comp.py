"""Folder analysis components for library scanning.

Provides filesystem discovery and scan planning as separate concerns:

- ``discover_library_folders`` — pure filesystem walk
- ``plan_incremental_scan`` — cache-aware planning (skip unchanged folders)
- ``plan_full_scan`` — plan that scans every folder
"""

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from nomarr.helpers.files_helper import is_audio_file
from nomarr.helpers.fs_contract import classify_os_error

logger = logging.getLogger(__name__)

# Per-entry measurement failure kinds that indicate the folder's whole
# medium/storage is unavailable. They propagate so discovery records the folder
# as uninspected rather than as an authoritative empty folder.
_MOUNT_LEVEL_KINDS = frozenset({"storage_unavailable", "unconfirmed_missing", "transient_io"})


# Component-local DTOs (not promoted to helpers/dto)
@dataclass
class FolderMetadata:
    """Metadata for a single folder in the library."""

    abs_path: str
    rel_path: str  # POSIX relative to library root
    mtime: int  # Modification time in milliseconds
    file_count: int  # Number of audio files
    failed_count: int = 0  # Audio entries that could not be individually stat'd


@dataclass(frozen=True)
class FolderMeasurement:
    """Audio-file measurement for one folder: count plus per-entry failures."""

    file_count: int
    failed_count: int


@dataclass
class FolderDiscovery:
    """Result of walking the filesystem for audio-bearing folders.

    ``uninspected_rel_paths`` holds library-relative POSIX folder paths that
    could not be authoritatively inspected — either the walk itself failed
    (``os.walk`` ``onerror``) or per-directory measurement raised ``OSError``.
    Callers must treat these paths as un-inspected scope: their absence may not
    be inferred. The set is bounded by the number of failed directories and
    contains paths only (no song/path materialization).

    ``enumerated_entries`` maps every walked folder's library-relative path to
    its raw ``os.walk`` listing names (directories and files), so callers can
    corroborate a folder's absence without a further filesystem probe.
    """

    folders: list[FolderMetadata]
    uninspected_rel_paths: set[str]
    enumerated_entries: dict[str, frozenset[str]] = field(default_factory=dict)


@dataclass
class FolderScanPlan:
    """Plan describing which folders need scanning."""

    all_folders: list[FolderMetadata]  # All folders with audio files
    folders_to_scan: list[FolderMetadata]  # Folders that need scanning
    folders_skipped: int  # Count of folders skipped due to cache
    total_files_to_scan: int  # Total audio files in folders_to_scan


def discover_library_folders(
    library_root: Path,
    scan_paths: list[Path],
) -> FolderDiscovery:
    """Walk the filesystem and discover all folders containing audio files.

    Pure discovery — no cache comparison, no scan policy decisions.

    Discovery failures are explicit rather than silent: a directory that cannot
    be walked (``os.walk`` ``onerror``) or measured (``OSError`` from either
    ``_get_folder_mtime`` or ``_count_audio_files_in_folder``) is recorded in
    ``uninspected_rel_paths`` so callers never infer its absence. Successful
    discovery is unchanged.

    Args:
        library_root: Absolute path to library root
        scan_paths: Paths to walk (typically ``[library_root]``)

    Returns:
        :class:`FolderDiscovery` with :class:`FolderMetadata` for every folder
        with at least one audio file, plus the bounded set of library-relative
        paths that could not be authoritatively inspected.

    """
    folders: list[FolderMetadata] = []
    uninspected: set[str] = set()
    enumerated: dict[str, frozenset[str]] = {}

    def _record_uninspected(raw_path: str) -> None:
        """Record a failed path as uninspected; never raise from error handling."""
        try:
            uninspected.add(_compute_folder_path(Path(raw_path), library_root))
        except ValueError:
            logger.warning("Uninspected path outside library root, cannot encode: %s", raw_path)

    def _on_walk_error(error: OSError) -> None:
        if error.filename:
            _record_uninspected(error.filename)
        logger.warning("Cannot walk folder %s: %s", error.filename, error)

    for scan_path in scan_paths:
        for dirpath, dirnames, filenames in os.walk(str(scan_path), onerror=_on_walk_error):
            try:
                folder_mtime = _get_folder_mtime(dirpath)
                measurement = _count_audio_files_in_folder(dirpath)
            except OSError as e:
                logger.warning("Cannot access folder %s: %s", dirpath, e)
                _record_uninspected(dirpath)
                continue

            folder_rel_path = _compute_folder_path(Path(dirpath), library_root)
            enumerated[folder_rel_path] = frozenset(dirnames) | frozenset(filenames)

            # A folder measured zero solely from isolated per-entry failures must
            # still be emitted (file_count == 0, failed_count > 0) so it can never
            # be classified vanished.
            if measurement.file_count == 0 and measurement.failed_count == 0:
                continue

            folders.append(
                FolderMetadata(
                    abs_path=dirpath,
                    rel_path=folder_rel_path,
                    mtime=folder_mtime,
                    file_count=measurement.file_count,
                    failed_count=measurement.failed_count,
                ),
            )

    return FolderDiscovery(
        folders=folders,
        uninspected_rel_paths=uninspected,
        enumerated_entries=enumerated,
    )


def plan_incremental_scan(
    all_folders: list[FolderMetadata],
    cached_folders: dict[str, dict],
) -> FolderScanPlan:
    """Build a scan plan that skips unchanged folders.

    Compares each discovered folder's mtime and file_count against the
    DB cache.  Folders whose cache entry matches are skipped.

    Args:
        all_folders: Discovered folders from ``FolderDiscovery.folders`` (see
            :func:`discover_library_folders`)
        cached_folders: DB cache — ``rel_path -> {mtime, file_count}``

    Returns:
        :class:`FolderScanPlan` with changed folders in ``folders_to_scan``
        and unchanged folders counted in ``folders_skipped``.

    """
    folders_to_scan: list[FolderMetadata] = []
    folders_skipped = 0

    for folder in all_folders:
        cached = cached_folders.get(folder.rel_path)
        if cached and cached["mtime"] == folder.mtime and cached["file_count"] == folder.file_count:
            folders_skipped += 1
            logger.debug("Skipping unchanged folder: %s", folder.rel_path)
        else:
            folders_to_scan.append(folder)

    return FolderScanPlan(
        all_folders=all_folders,
        folders_to_scan=folders_to_scan,
        folders_skipped=folders_skipped,
        total_files_to_scan=sum(f.file_count for f in folders_to_scan),
    )


def plan_full_scan(
    all_folders: list[FolderMetadata],
) -> FolderScanPlan:
    """Build a scan plan that includes every folder.

    No cache comparison — all discovered folders are marked for scanning.

    Args:
        all_folders: Discovered folders from ``FolderDiscovery.folders`` (see
            :func:`discover_library_folders`)

    Returns:
        :class:`FolderScanPlan` with all folders in ``folders_to_scan``
        and ``folders_skipped == 0``.

    """
    return FolderScanPlan(
        all_folders=all_folders,
        folders_to_scan=list(all_folders),
        folders_skipped=0,
        total_files_to_scan=sum(f.file_count for f in all_folders),
    )


# Component-private helpers
def _get_folder_mtime(folder_path: str) -> int:
    """Get folder modification time in milliseconds."""
    return int(os.stat(folder_path).st_mtime * 1000)


def _count_audio_files_in_folder(folder_path: str) -> FolderMeasurement:
    """Measure audio entries in one folder (non-recursive), one stat per entry.

    A directory-listing failure, or a mount/storage-level per-entry ``os.stat``
    failure (``storage_unavailable``, ``unconfirmed_missing``, ``transient_io``),
    deliberately propagates so discovery can record the folder as uninspected
    rather than treating an inaccessible directory as empty. An isolated
    per-entry failure increments ``failed_count`` while the folder stays
    reconciled; a non-regular entry is likewise a per-entry failure.
    """
    file_count = 0
    failed_count = 0
    for name in os.listdir(folder_path):
        if not is_audio_file(name):
            continue
        try:
            entry_stat = os.stat(os.path.join(folder_path, name))
        except OSError as e:
            if classify_os_error(e) in _MOUNT_LEVEL_KINDS:
                raise
            failed_count += 1
            continue
        if stat.S_ISREG(entry_stat.st_mode):
            file_count += 1
        else:
            failed_count += 1
    return FolderMeasurement(file_count=file_count, failed_count=failed_count)


def _compute_folder_path(absolute_folder: Path, library_root: Path) -> str:
    """Compute POSIX-style relative folder path from library root.

    Args:
        absolute_folder: Absolute folder path
        library_root: Library root path

    Returns:
        POSIX-style relative path (e.g., ``"Rock/Beatles"``), or ``""`` for root

    """
    if absolute_folder == library_root:
        return ""
    relative = absolute_folder.relative_to(library_root)
    return relative.as_posix()
