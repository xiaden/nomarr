"""Quick (incremental) library scan workflow.

Uses folder-level caching to skip unchanged folders.  Only folders whose
mtime or file count changed since the last scan are walked.

Pass 1 of the two-pass scan: fast disk walk → upsert files to DB + seed state edges.
Pass 2 (audio tag extraction + entity seeding) runs in the background tag extraction worker.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_batch_scanner_comp import scan_folder_files
from nomarr.components.library.folder_analysis_comp import discover_library_folders
from nomarr.components.library.library_root_comp import validate_library_root
from nomarr.components.library.library_scan_file_ops_comp import (
    cleanup_stale_folders,
    get_cached_folders,
    remove_deleted_files,
    save_folder_record,
    upsert_scanned_files,
)
from nomarr.components.library.library_scan_state_comp import transition_pipeline_axis
from nomarr.components.library.library_song_query_comp import (
    get_folder_rel_paths,
    get_songs_in_exact_folder,
)
from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.library.move_detection_comp import (
    detect_move_for_new_file,
    relocate_song,
    song_identity_for,
)
from nomarr.components.library.scan_lifecycle_comp import (
    mark_scan_completed,
    resolve_library_for_scan,
    update_scan_progress,
)
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_HYDRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_HYDRATED,
    STATE_NOT_SCANNED,
    STATE_SCANNED,
)
from nomarr.helpers.constants.pipeline_states import SCAN_NOT_SCANNED, SCAN_STATE_FIELD
from nomarr.helpers.exceptions import TaskCancelledError
from nomarr.helpers.time_helper import internal_s, now_ms
from nomarr.workflows.metadata.cleanup_orphaned_entities_wf import cleanup_orphaned_entities_workflow

if TYPE_CHECKING:
    import threading

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class ScanCancelledError(TaskCancelledError):
    """Raised when a cooperative scan cancellation is requested."""


def _check_cancelled(stop_event: threading.Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise ScanCancelledError("Scan cancelled by user")


def _path_exists(path: str) -> bool:
    """Return whether an absolute path currently exists on disk (patchable)."""
    return Path(path).exists()


def _candidate_source_present(
    song: Song,
    unreconciled_folder_paths: set[str],
    discovery_uninspected_folder_paths: set[str],
) -> bool:
    """True when a chromaprint candidate's source is still known/presumed present.

    Two distinct scopes are consulted. Ordinary unreconciled scope is
    immediate-parent-only: a candidate is presumed live when its immediate parent
    folder (the last component of ``normalized_path``) was not reconciled by this
    scan. Discovery-uninspected scope is ancestry-aware: a candidate is also
    presumed live when its parent or any ancestor (including the root ``""``) is
    within discovery-uninspected scope, so a discovery-uninspected ancestor
    blocks a descendant candidate from relocation sourcing. A candidate whose
    absolute path still exists on disk is likewise presumed present. Only a
    genuinely absent, successfully-inspected source may be treated as a
    relocation origin.
    """
    parent = song.normalized_path.rsplit("/", 1)[0] if "/" in song.normalized_path else ""
    if parent in unreconciled_folder_paths or _scope_uninspected(parent, discovery_uninspected_folder_paths):
        return True
    return _path_exists(song.path)


def _scope_uninspected(rel_path: str, uninspected_folder_paths: set[str]) -> bool:
    """True when rel_path itself or any ancestor could not be authoritatively inspected."""
    candidate = rel_path
    while True:
        if candidate in uninspected_folder_paths:
            return True
        if not candidate:
            return False
        candidate = candidate.rsplit("/", 1)[0] if "/" in candidate else ""


def scan_library_quick_workflow(
    db: Database,
    library: Library,
    tagger_version: str,  # noqa: ARG001 - retained public signature; version gate retired
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Run a quick (incremental) library scan.

    Uses folder-level caching to skip unchanged folders.  Only folders
    whose mtime or file count changed since the last scan are walked.

    Pass 1: fast disk walk — upsert files to DB, seed initial state edges.
    Pass 2: background tag extraction worker reads audio tags and seeds entities.

    Move reconciliation is bounded and per-folder: modified files and
    same-locator rebases are applied in place immediately, and a true move is
    resolved one new file at a time via a bounded, library-scoped chromaprint
    lookup. Missing rows are not deleted during the walk; a final exact-folder
    cleanup pass removes only direct members of successfully-walked (changed) or
    vanished folders. Unchanged (cache-skipped), failed, and un-inspected folders
    are never reconciled or cleaned.

    Discovery and measurement failures are un-inspected scope, matched with the
    ancestry-aware ``_scope_uninspected``: a folder that could not be
    authoritatively inspected, and every descendant of it, is never treated as
    vanished and never cleaned up as stale. Quick scan has no orphan sweep, so
    there is no further deletion path to guard. Relocation sourcing consults the
    ancestry-aware discovery-uninspected scope, so a discovery-uninspected
    ancestor also blocks a descendant candidate from being treated as a
    relocation origin; only the ordinary unreconciled scope is
    immediate-parent-only.

    Deferral contract: quick scan does NOT perform untracked-parent-folder
    recovery. A row whose parent folder has no ``library_folders`` record (and no
    tracked/discovered audio-bearing ancestor) is left untouched by quick scan;
    that recovery is deferred to the exhaustive full scan, which reconciles every
    discovered folder. This preserves quick-scan authority and safety.

    Args:
        db: Database instance
        library: Domain ``Library`` (natural identity) to scan
        tagger_version: Retained for public signature compatibility; the version
            gate is retired and the value is unused.
        stop_event: Cooperative cancellation signal. When set, the scan aborts
            at the next folder checkpoint and raises ``ScanCancelledError``.

    Returns:
        Dict with scan statistics (files_discovered, files_added,
        files_updated, files_skipped, files_moved, files_removed,
        files_failed, scan_duration_s, warnings, scan_id)

    Raises:
        ScanCancelledError: If ``stop_event`` is set mid-scan. The scan records
            the cancellation as a scan error and resets the scan axis to
            ``not_scanned`` before re-raising.
        ValueError: If library not found
        OSError: If library root is inaccessible

    """
    start_time = internal_s()
    stats: dict[str, int] = defaultdict(int)
    warnings: list[str] = []
    scan_id = f"{library.name}_{now_ms()}"

    try:
        # Step 1 — Resolve library and validate root
        library = resolve_library_for_scan(db, library)
        library_root = Path(library.root_path).resolve()
        validate_library_root(library_root)

        # Step 2 — Pre-scan DB lookups
        db_folder_paths = get_folder_rel_paths(db, library)
        cached_folders = get_cached_folders(db, library)

        # Step 3 — Discover folders on disk and track uninspected scope
        discovery = discover_library_folders(library_root, [library_root])
        all_folders = discovery.folders
        discovered_folder_paths = {f.rel_path for f in all_folders}
        uninspected_folder_paths = set(discovery.uninspected_rel_paths)

        update_scan_progress(db, library, total=sum(f.file_count for f in all_folders))

        # Step 4 — Track vanished folders. Their persisted rows are reconciled
        # against changed-folder discoveries during the walk and removed by the
        # deferred cleanup pass; they never become a library-wide candidate set.
        # A folder that could not be authoritatively inspected — itself or any
        # ancestor — is NEVER treated as vanished.
        vanished_folder_paths = {
            rel_path
            for rel_path in db_folder_paths - discovered_folder_paths
            if not _scope_uninspected(rel_path, uninspected_folder_paths)
        }
        processed_file_count = 0

        # Folder-scoped bookkeeping only. Successfully-walked folders are
        # cleaned up after the walk; unchanged (cache-skipped) folders, folders
        # whose walk failed, and folders that could not be authoritatively
        # inspected during discovery are unreconciled — never cleaned up. The
        # relocation-source guard separately consults two distinct scopes:
        # ordinary unreconciled scope on each song's immediate parent only, and
        # ancestry-aware discovery-uninspected scope (parent or any ancestor).
        # Seeding the unreconciled set before the walk keeps skip
        # decisions order-independent.
        reconciled_folder_paths: set[str] = set()
        unreconciled_folder_paths: set[str] = set()
        for folder in all_folders:
            cached = cached_folders.get(folder.rel_path)
            if cached and cached.mtime == folder.mtime and cached.file_count == folder.file_count:
                unreconciled_folder_paths.add(folder.rel_path)

        # Step 5 — Per-folder scan. Unchanged/modified files are processed
        # immediately, same-locator rebases are applied immediately, and each
        # true new/move destination is resolved individually. Missing rows are
        # NOT deleted here. The walk working set uses the exact-folder query
        # because ``scan_folder_files`` reads a single directory non-recursively,
        # so descendant rows are never needed by the walk.
        for folder in all_folders:
            _check_cancelled(stop_event)
            cached = cached_folders.get(folder.rel_path)
            if cached and cached.mtime == folder.mtime and cached.file_count == folder.file_count:
                stats["folders_skipped"] += 1
                logger.debug("Skipping unchanged folder: %s", folder.rel_path)
                processed_file_count += folder.file_count
                update_scan_progress(db, library, progress=processed_file_count)
                continue

            stats["folders_scanned"] += 1

            for attempt in range(2):
                try:
                    existing_for_folder = get_songs_in_exact_folder(db, library, folder.rel_path)
                    batch = scan_folder_files(
                        folder_path=Path(folder.abs_path),
                        library_root=library_root,
                        existing_files=existing_for_folder,
                        db=db,
                    )

                    stats["files_updated"] += batch.stats["files_updated"]
                    stats["files_failed"] += batch.stats["files_failed"]
                    stats["files_skipped"] += batch.stats.get("files_skipped", 0)
                    stats["files_discovered"] += len(batch.discovered_paths)
                    warnings.extend(batch.warnings)

                    if batch.file_entries:
                        existing_by_normalized = {
                            carrier.candidate.song.normalized_path: carrier for carrier in existing_for_folder.values()
                        }
                        modified_entries = [e for e in batch.file_entries if e["path"] in existing_for_folder]
                        remaining = [e for e in batch.file_entries if e["path"] not in existing_for_folder]

                        # Modified files (same absolute path) upsert in place.
                        if modified_entries:
                            song_identities = upsert_scanned_files(db, library, modified_entries, batch.edge_bootstraps)
                            transition_song_state(db, song_identities, STATE_NOT_SCANNED, STATE_SCANNED)
                            transition_song_state(db, song_identities, STATE_ERRORED, STATE_NOT_ERRORED)
                            # Reset hydrated → not_hydrated so the tag extraction
                            # worker re-extracts their audio tags.
                            transition_song_state(db, song_identities, STATE_HYDRATED, STATE_NOT_HYDRATED)

                        # Same-locator rebase: the normalized path is unchanged but
                        # the absolute path differs (root/mount remap). This is the
                        # same SongIdentity — rebase in place, no chromaprint.
                        genuine_new: list[dict[str, Any]] = []
                        for entry in remaining:
                            carrier = existing_by_normalized.get(entry["normalized_path"])
                            if (
                                carrier is not None
                                and carrier.candidate.song.path != entry["path"]
                                and relocate_song(
                                    db,
                                    song_identity_for(library, entry["normalized_path"]),
                                    new_path=entry["path"],
                                    normalized_path=entry["normalized_path"],
                                    file_size=entry["file_size"],
                                    modified_time=entry["modified_time"],
                                    duration_seconds=carrier.candidate.song.duration_seconds,
                                )
                            ):
                                stats["files_moved"] += 1
                                continue
                            genuine_new.append(entry)

                        # True moves: a bounded, library-scoped chromaprint lookup
                        # per new file. A live duplicate is never repointed.
                        unmatched: list[dict[str, Any]] = []
                        for entry in genuine_new:
                            move = detect_move_for_new_file(
                                entry,
                                library,
                                db,
                                source_present=lambda song: _candidate_source_present(
                                    song, unreconciled_folder_paths, uninspected_folder_paths
                                ),
                            )
                            if move is not None and relocate_song(
                                db,
                                move.song_identity,
                                new_path=move.new_path,
                                normalized_path=entry["normalized_path"],
                                file_size=move.new_file_size,
                                modified_time=move.new_modified_time,
                                duration_seconds=move.new_duration,
                            ):
                                stats["files_moved"] += 1
                                continue
                            unmatched.append(entry)
                        genuine_new = unmatched

                        if genuine_new:
                            song_identities = upsert_scanned_files(db, library, genuine_new, batch.edge_bootstraps)
                            transition_song_state(db, song_identities, STATE_NOT_SCANNED, STATE_SCANNED)
                            transition_song_state(db, song_identities, STATE_ERRORED, STATE_NOT_ERRORED)
                            transition_song_state(db, song_identities, STATE_HYDRATED, STATE_NOT_HYDRATED)
                            stats["files_added"] += len(genuine_new)

                    save_folder_record(
                        db,
                        library,
                        folder.rel_path,
                        folder.mtime,
                        folder.file_count,
                    )
                    reconciled_folder_paths.add(folder.rel_path)
                    break

                except Exception as e:
                    if attempt == 0:
                        logger.debug(
                            "Folder %r failed on first attempt, retrying: %s",
                            folder.rel_path,
                            e,
                            exc_info=True,
                        )
                    else:
                        logger.error(
                            "Folder %r failed after retry, skipping: %s",
                            folder.rel_path,
                            e,
                        )
                        stats["files_failed"] += folder.file_count
                        warnings.append(f"Folder {folder.rel_path!r} skipped after error: {e}")
                        # The walk failed, so this folder is unreconciled: it is
                        # never cleaned up and none of its rows may source a move.
                        unreconciled_folder_paths.add(folder.rel_path)

            processed_file_count += folder.file_count
            update_scan_progress(db, library, progress=processed_file_count)

        # Step 6 — Deferred, exact-folder cleanup. Only successfully-walked
        # (changed) folders and vanished folders are eligible; cache-skipped and
        # failed folders are never touched. Cleanup reads only one folder's DIRECT
        # members (``get_songs_in_exact_folder``), so the per-iteration working set
        # is bounded to that folder and never re-materializes a nested descendant
        # subtree. A row relocated during the walk no longer belongs to its source
        # exact-folder query (it now points at its destination) and is preserved.
        # Per row, reuse the candidate source-presence guard: delete only rows
        # whose current absolute path no longer exists. Genuinely-untracked-folder
        # recovery is NOT performed by quick scan; it is deferred to the exhaustive
        # full scan.
        for rel_path in (*reconciled_folder_paths, *vanished_folder_paths):
            _check_cancelled(stop_event)
            folder_rows = get_songs_in_exact_folder(db, library, rel_path)
            dead = [
                carrier.candidate.song.path
                for carrier in folder_rows.values()
                if not _candidate_source_present(
                    carrier.candidate.song, unreconciled_folder_paths, uninspected_folder_paths
                )
            ]
            if dead:
                stats["files_removed"] += remove_deleted_files(db, library, dead)

        # Step 7 — Clean up stale folder records. Preserve discovered folders and
        # every folder that could not be authoritatively inspected (itself or an
        # ancestor), so an un-inspected folder record is never deleted as stale.
        preserved_folder_paths = discovered_folder_paths | {
            rel_path for rel_path in db_folder_paths if _scope_uninspected(rel_path, uninspected_folder_paths)
        }
        cleanup_stale_folders(db, library, preserved_folder_paths)

        # Step 8 — Entity graph cleanup (skip when scan was a no-op)
        has_changes = stats["files_added"] + stats["files_updated"] + stats["files_removed"] + stats["files_moved"] > 0
        if has_changes:
            try:
                cleanup_orphaned_entities_workflow(db, dry_run=False)
            except Exception as e:
                logger.warning("Entity cleanup failed: %s", e, exc_info=True)

        # Step 9 — Finalize
        scan_duration = internal_s().value - start_time.value
        mark_scan_completed(db, library)
        update_scan_progress(
            db,
            library,
            progress=processed_file_count,
            scan_error=None,
        )

        scan_log = logger.info if has_changes or stats["files_failed"] else logger.debug
        scan_log(
            "Quick scan complete in %.1fs: folders=%d/%d, added=%d, updated=%d, skipped=%d, moved=%d, removed=%d, failed=%d",
            scan_duration,
            stats["folders_scanned"],
            stats["folders_scanned"] + stats["folders_skipped"],
            stats["files_added"],
            stats["files_updated"],
            stats["files_skipped"],
            stats["files_moved"],
            stats["files_removed"],
            stats["files_failed"],
        )

        return {**stats, "scan_duration_s": scan_duration, "warnings": warnings, "scan_id": scan_id}

    except Exception as e:
        if isinstance(e, ScanCancelledError):
            logger.info("Quick scan cancelled for library %s", library.name)
            try:
                update_scan_progress(db, library, status="error", scan_error=str(e))
            except Exception:
                logger.exception("Failed to record scan error after cancellation for library %s", library.name)
            try:
                transition_pipeline_axis(db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
            except Exception:
                logger.exception("Failed to reset scan axis after cancellation for library %s", library.name)
            raise
        logger.error("Quick scan crashed: %s", e, exc_info=True)
        try:
            update_scan_progress(db, library, scan_error=str(e))
        except Exception:
            logger.exception("Failed to record scan error after scan failure for library %s", library.name)
        try:
            transition_pipeline_axis(db, library, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
        except Exception:
            logger.exception(
                "Failed to reset scan axis to not_scanned after scan failure for library %s",
                library.name,
            )
        raise
