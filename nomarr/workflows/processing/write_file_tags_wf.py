"""File tag writing workflow - writes DB tags to audio files.

This workflow writes tags from the database to audio files based on
the library's file_write_mode setting. It handles mode filtering,
calibration requirements, and atomic safe writes.

ARCHITECTURE:
- DB is the source of truth for all tags
- Files are projections controlled per-library
- Mood tags require calibration - filtered out when calibration is empty
- Uses existing TagWriter with atomic safe writes

MODES:
- "none": Remove all nom-style namespaced tags (call TagWriter.write_safe(None))
- "minimal": Only mood-tier tags (mood-strict, mood-regular, mood-loose)
- "full": All available tags from DB
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nomarr.components.infrastructure.path_comp import build_library_path_from_db
from nomarr.components.library.library_records_comp import find_library_containing_path
from nomarr.components.library.reconciliation_comp import release_claim, set_file_written
from nomarr.components.processing.file_write_comp import resolve_library_root
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue
from nomarr.helpers.exceptions import LibraryOperationConflict
from nomarr.helpers.fs_contract import FsFact

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity, SongReplacementInput
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
    from nomarr.helpers.dto.library_dto import RecoveryEvidence, RecoveryMode, RecoveryTerminalOutcome, WriteOutcome
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result from write_file_tags_workflow."""

    file_key: SongIdentity  # Semantic locator of the file
    tags_written: int  # Number of tags written to file
    tags_filtered: int  # Number of tags filtered out by mode
    success: bool  # Whether write succeeded
    fs_fact: FsFact | None = None  # Structured filesystem fact for a filesystem failure
    outcome: WriteOutcome | None = None  # Structured failure reason (DD §8.7)
    requested_mode: RecoveryMode = "files"
    evidence_class: RecoveryEvidence | None = None
    terminal_outcome: RecoveryTerminalOutcome | None = None
    resumable: bool = True

    @property
    def error(self) -> str | None:
        """Derived, read-only ``str | None`` view over ``outcome``/``fs_fact`` (DD §8.7).

        ``error`` is not an independently settable field — it is a pure function of the
        structured fields, so it cannot drift from them. ``outcome == "modified_externally"``
        renders the legacy ``"file_modified_externally"`` token for backward-compatible
        textual reporting and logging; every other outcome maps to its own name.
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


def _filter_tags_for_mode(
    db_tags: Tags | None,
    target_mode: str,
    has_calibration: bool,
) -> Tags | None:
    """Filter tags based on target mode and calibration state.

    Args:
        db_tags: All tags from database (Tags DTO), or ``None`` when no nomarr
            tags exist for the file.
        target_mode: "none", "minimal", or "full"
        has_calibration: Whether calibration exists

    Returns:
        Filtered ``Tags`` for file writing, or ``None`` when nothing should be
        written. ``None`` is the strict representation of "clear/remove all
        tags" — an empty ``Tags`` collection is invalid in the strict model,
        so the empty result is expressed as ``None`` instead.

    """
    # "none" mode clears the namespace entirely.
    if target_mode == "none":
        return None

    # No nomarr tags in DB -> nothing to write; clear to stay consistent.
    if db_tags is None:
        return None

    # Filter out mood tags if uncalibrated (applies to ALL modes)
    if not has_calibration:
        filtered_items = tuple(tag for tag in db_tags.items if not tag.name.startswith("mood-"))
    else:
        filtered_items = db_tags.items  # Already a tuple

    if target_mode == "minimal":
        # Only mood-tier tags
        filtered_items = tuple(tag for tag in filtered_items if tag.name.startswith("mood-"))

    if not filtered_items:
        return None

    # "full" mode - return all tags (already mood-filtered if uncalibrated)
    return Tags(items=filtered_items)


def _resolve_library_path(
    song: Song,
    db: Database,
) -> tuple[LibraryPath | None, Library | None]:
    """Resolve ``song`` to a validated ``LibraryPath`` and its domain ``Library``.

    Both the library path and the owning library root are derived from the
    file's physical ``path`` using ``find_library_containing_path`` (path-based
    natural identity), never from the integer storage ``library_id``. Returns
    ``(None, None)`` when no library contains the path, and ``(None, library)``
    when the library is known but the path is otherwise invalid for config or
    semantic reasons (e.g. the stored path is no longer relative to the library
    root).
    """
    stored_path = song.path
    if not stored_path:
        return None, None

    library = find_library_containing_path(db, stored_path)
    if not library:
        return None, None

    library_path = build_library_path_from_db(
        stored_path=stored_path,
        db=db,
        library_id=library.name,
    )

    if not library_path.is_valid():
        return None, library
    return library_path, library


def _replacement_input(song: Song, library_path: LibraryPath) -> SongReplacementInput:
    """Build a replacement snapshot from current filesystem facts and metadata."""
    import os

    from nomarr.components.library.metadata_extraction_comp import extract_metadata
    from nomarr.helpers.dataclasses.song_command_dataclass import SongReplacementInput, SongScanUpdate

    metadata = extract_metadata(library_path)
    stat_result = os.stat(library_path.absolute)
    duration = metadata.get("duration")
    return SongReplacementInput(
        path=song.path,
        scan=SongScanUpdate(
            normalized_path=song.normalized_path,
            file_size=stat_result.st_size,
            modified_time=int(stat_result.st_mtime * 1000),
            duration_seconds=float(duration) if duration is not None else None,
        ),
    )


def _refresh_input(library_path: LibraryPath):
    from nomarr.components.library.metadata_extraction_comp import extract_metadata
    from nomarr.components.metadata.entity_seeding_comp import extract_entity_tag_mapping
    from nomarr.components.metadata.metadata_cache_comp import compute_metadata_cache_fields
    from nomarr.components.tagging.tag_parsing_comp import parse_tag_values
    from nomarr.helpers.dto.hydration_dto import HydrateSongInput

    metadata = extract_metadata(library_path)
    return HydrateSongInput(
        parsed_nom_tags=parse_tag_values(metadata.get("nom_tags", {})),
        entity_tags=extract_entity_tag_mapping(metadata),
        metadata_cache=compute_metadata_cache_fields(metadata),
        duration_seconds=float(metadata["duration"]) if metadata.get("duration") is not None else None,
    )


def _release_failed_write(db: Database, file_key: SongIdentity, worker_id: str) -> None:
    """Release a failed write while leaving it in the reconciliation queue.

    A failed projection write must not be marked current: the database
    projection is still stale and must be retried.  Only the claim is released;
    cleanup is best effort because it runs while handling another failure.
    """
    release_claim(db, file_key, worker_id)


def write_file_tags_workflow(
    db: Database,
    file_key: SongIdentity,
    worker_id: str,
    target_mode: str,
    has_calibration: bool,
    namespace: str = "nom",
    requested_mode: RecoveryMode = "files",
) -> WriteResult:
    """Write tags from database to an audio file based on mode.

    This workflow reads tags from the database and writes them to the audio
    file using the appropriate mode filtering. It uses atomic safe writes
    via TagWriter to prevent file corruption.

    Args:
        db: Database instance
        file_key: Semantic locator of the file to write
        worker_id: Reconciliation worker identity holding the write claim; used to
            release the exact claim on every terminal failure path and to advance
            the file's projection state on success.
        target_mode: Desired write mode ("none", "minimal", "full")
        has_calibration: Whether calibration exists (affects mood tag filtering)
        namespace: Tag namespace (default: "nom").
        requested_mode: Recovery policy for an externally modified file:
            ``"files"`` rebaselines and retries when the fingerprint is the
            same; ``"database"`` refreshes the database-side baseline instead.

    Returns:
        WriteResult with success status, counts, recovery evidence, terminal
        outcome, and whether the file remains resumable. An externally modified
        file is classified by fingerprint as ``same``, ``different``, or
        ``indeterminate``; same-file recovery can end as ``rebaselined`` or
        ``raced``, while a different fingerprint is ``replaced`` when the
        replacement intent is available. Unresolved failures remain resumable.

    Raises:
        LibraryOperationConflict: If lifecycle admission changes while the
            physical write is being prepared or performed.

    Notes:
        - "none" mode clears the namespace entirely
        - "minimal" writes only mood-tier tags
        - "full" writes all DB tags
        - Mood tags are filtered if calibration is empty (any mode)

    """
    try:
        # Resolve the semantic locator through the public facade.  The facade
        # keeps generated row identity private; a stale locator is a clean miss.
        song = db.library.get_song(file_key)

        if song is None:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                outcome="song_record_missing",
            )

        # Resolve library path + owning domain Library from the file's path.
        library_path, library = _resolve_library_path(song, db)
        if not library_path:
            _release_failed_write(db, file_key, worker_id)
            if library is None:
                # No containing library: a config/domain miss, not a filesystem fact.
                return WriteResult(
                    file_key=file_key,
                    tags_written=0,
                    tags_filtered=0,
                    success=False,
                    outcome="library_unresolved",
                )
            # A known library with a structurally invalid path carries the invalid_path fact.
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                fs_fact=FsFact(presence="unknown", kind="invalid_path", errno=None),
            )

        # A valid ``library_path`` always carries its owning domain ``Library``
        # (``_resolve_library_path`` returns ``(None, library)`` on invalid paths),
        # so reaching here guarantees ``library`` is present. Assert rather than
        # branch: the state is impossible, not a recoverable failure.
        assert library is not None

        # Get library root for safe write (domain Library, path-derived).
        library_root = resolve_library_root(db, library)
        if not library_root:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=0,
                success=False,
                outcome="library_unresolved",
            )

        permission_guard = getattr(db.library.regions, "assert_physical_write_allowed", None)
        if permission_guard is not None:
            permission_guard(library)

        # Require known mtime to prevent writing to externally-modified files.
        # ``Song.modified_time`` is a non-optional int, so it is always present.
        expected_mtime_ms = song.modified_time

        # Get tags from the locator-addressed facade and project only semantic
        # name/value pairs into the file-writer DTO.
        assignments: tuple[SongTagAssignment, ...] = db.library.list_tags_for_song(file_key)
        nomarr_assignments = [assignment for assignment in assignments if assignment.namespace == "nom"]
        grouped: dict[str, list[TagValue]] = {}
        for assignment in nomarr_assignments:
            # SongTagAssignment.value is typed ``object`` but is always a scalar
            # TagValue at runtime; the canonical ``Tag`` validates the type.
            grouped.setdefault(assignment.name, []).append(cast("TagValue", assignment.value))
        db_tags = (
            Tags(items=tuple(Tag(name=name, values=tuple(values)) for name, values in grouped.items()))
            if grouped
            else None
        )

        # Filter tags for target mode. ``None`` means "clear/remove all tags"
        # and is passed to the writer so it still clears the namespace.
        tags_to_write = _filter_tags_for_mode(db_tags, target_mode, has_calibration)
        tags_filtered = (len(db_tags) if db_tags is not None else 0) - (
            len(tags_to_write) if tags_to_write is not None else 0
        )

        # Create tag writer with overwrite=True to clear namespace first
        tag_writer = TagWriter(overwrite=True, namespace=namespace)

        # Write tags using atomic safe write
        result = tag_writer.write_safe(library_path, tags_to_write, library_root, expected_mtime_ms)
        evidence_class: RecoveryEvidence | None = None
        terminal_outcome: RecoveryTerminalOutcome | None = None
        if not result.success and result.outcome == "modified_externally":
            import os

            from nomarr.components.library.metadata_extraction_comp import compute_chromaprint_for_file

            # There is exactly one bounded comparison attempt for every mtime
            # mismatch, including when the persisted evidence is absent.
            persisted = song.chromaprint
            try:
                computed = compute_chromaprint_for_file(library_path)
                if not persisted or not computed:
                    evidence_class = cast("RecoveryEvidence", "fingerprint_indeterminate")
                else:
                    evidence_class = cast(
                        "RecoveryEvidence",
                        "fingerprint_same" if computed == persisted else "fingerprint_different",
                    )
            except (ImportError, OSError, RuntimeError, ValueError, TypeError):
                evidence_class = cast("RecoveryEvidence", "fingerprint_indeterminate")
            terminal_outcome = cast("RecoveryTerminalOutcome", "pending")
            if evidence_class == "fingerprint_same" and requested_mode == "none":
                pass
            elif evidence_class == "fingerprint_same" and requested_mode == "files":
                try:
                    fresh_mtime_ms = int(os.stat(library_path.absolute).st_mtime * 1000)
                    result = tag_writer.write_safe(library_path, tags_to_write, library_root, fresh_mtime_ms)
                    terminal_outcome = cast("RecoveryTerminalOutcome", "rebaselined" if result.success else "raced")
                except (OSError, ValueError):
                    terminal_outcome = cast("RecoveryTerminalOutcome", "raced")
            elif evidence_class == "fingerprint_same" and requested_mode == "database":
                try:
                    refresh_input = _refresh_input(library_path)
                    modified_time_ms = int(os.stat(library_path.absolute).st_mtime * 1000)
                    db.library.refresh_hydrated_song(file_key, refresh_input, modified_time_ms)
                    terminal_outcome = cast("RecoveryTerminalOutcome", "refreshed")
                    _release_failed_write(db, file_key, worker_id)
                    return WriteResult(
                        file_key=file_key,
                        tags_written=0,
                        tags_filtered=tags_filtered,
                        success=True,
                        requested_mode=requested_mode,
                        evidence_class=evidence_class,
                        terminal_outcome=terminal_outcome,
                        resumable=False,
                    )
                except (OSError, RuntimeError, ValueError, TypeError):
                    terminal_outcome = cast("RecoveryTerminalOutcome", "failed")
            elif evidence_class == "fingerprint_different":
                replacement = getattr(db.library, "replace_song_for_reimport", None)
                if replacement is not None:
                    try:
                        replacement(file_key, _replacement_input(song, library_path))
                        terminal_outcome = cast("RecoveryTerminalOutcome", "replaced")
                    except (LookupError, OSError, RuntimeError, ValueError, TypeError):
                        terminal_outcome = cast("RecoveryTerminalOutcome", "failed")
                else:
                    terminal_outcome = cast("RecoveryTerminalOutcome", "failed")
            if terminal_outcome in {"refreshed", "replaced"}:
                _release_failed_write(db, file_key, worker_id)
                return WriteResult(
                    file_key=file_key,
                    tags_written=0,
                    tags_filtered=tags_filtered,
                    success=True,
                    requested_mode=requested_mode,
                    evidence_class=evidence_class,
                    terminal_outcome=terminal_outcome,
                    resumable=False,
                )
        if not result.success:
            _release_failed_write(db, file_key, worker_id)
            return WriteResult(
                file_key=file_key,
                tags_written=0,
                tags_filtered=tags_filtered,
                success=False,
                fs_fact=result.fs_fact,
                outcome=result.outcome,
                requested_mode=requested_mode,
                evidence_class=evidence_class,
                terminal_outcome=terminal_outcome,
                resumable=True,
            )

        # Sync mtime in DB so scanner skips this file on next scan
        if result.new_mtime_ms is not None:
            db.library.set_modified_time(file_key, result.new_mtime_ms)

        # Update file projection state in database
        set_file_written(db, file_key, worker_id)

        logger.debug(
            f"[write_file_tags] Wrote {len(tags_to_write) if tags_to_write is not None else 0} tags to {library_path.relative} "
            f"(mode={target_mode}, filtered={tags_filtered})",
        )

        return WriteResult(
            file_key=file_key,
            tags_written=len(tags_to_write) if tags_to_write is not None else 0,
            tags_filtered=tags_filtered,
            success=True,
            requested_mode=requested_mode,
            evidence_class=evidence_class,
            terminal_outcome=terminal_outcome or "written",
            resumable=False,
        )

    except LibraryOperationConflict:
        _release_failed_write(db, file_key, worker_id)
        raise
    except Exception:
        logger.exception("[write_file_tags] Failed to write tags for locator")
        _release_failed_write(db, file_key, worker_id)
        return WriteResult(
            file_key=file_key,
            tags_written=0,
            tags_filtered=0,
            success=False,
            outcome="write_failed",
        )
