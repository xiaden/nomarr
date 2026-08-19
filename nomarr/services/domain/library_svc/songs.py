"""Library song operations.

This module handles:
- Cleaning up orphaned tags in DB
- Path reconciliation and validation
- Song tag queries from DB
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.library_root_comp import resolve_path_within_library
from nomarr.components.library.library_song_state_comp import get_errored_song_ids, transition_song_state
from nomarr.components.library.song_tags_comp import get_song_tags_with_path
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_PROCESSED,
    STATE_PROCESSED,
)
from nomarr.helpers.dto.library_dto import FileTag, FileTagsResult, RetryErroredResult, TagCleanupResult
from nomarr.workflows.library.cleanup_orphaned_tags_wf import cleanup_orphaned_tags_workflow
from nomarr.workflows.library.reconcile_paths_wf import reconcile_library_paths_workflow

if TYPE_CHECKING:
    from pathlib import Path

    from nomarr.components.library.reconcile_paths_comp import ReconcilePolicy, ReconcileResult
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibrarySongsMixin:
    """Mixin providing library song operations."""

    db: Database
    cfg: LibraryServiceConfig

    def _get_library_or_error(self, library_id: int) -> dict[str, Any]:
        """Get a library by ID or raise an error."""
        result = get_library_record(self.db, int(library_id))
        if result is None:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)
        return result

    def cleanup_orphaned_tags(self, dry_run: bool = False) -> TagCleanupResult:
        """Clean up orphaned tags from the database.

        Args:
            dry_run: If True, count orphaned tags but don't delete them

        Returns:
            TagCleanupResult DTO with orphaned_count and deleted_count

        """
        result = cleanup_orphaned_tags_workflow(self.db, dry_run=dry_run)
        return TagCleanupResult(
            orphaned_count=result["orphaned_count"],
            deleted_count=result["deleted_count"],
        )

    def get_song_tags(self, song_id: int, nomarr_only: bool = False) -> FileTagsResult:
        """Get all tags for a specific song.

        Args:
            song_id: Library song ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            FileTagsResult DTO with song info and tags

        Raises:
            ValueError: If song not found

        """
        # Get song and tags from component
        result = get_song_tags_with_path(self.db, int(song_id), nomarr_only=nomarr_only)
        if not result:
            msg = f"Song with ID {song_id} not found"
            raise ValueError(msg)

        # Convert to FileTag DTOs
        tags = [
            FileTag(
                key=tag["key"],
                value=str(tag["value"]),
                tag_type=tag["type"],
                is_nomarr=tag["is_nomarr"],
            )
            for tag in result["tags"]
        ]

        return FileTagsResult(
            file_id=int(song_id),
            path=result["path"],
            tags=tags,
        )

    def reconcile_library_paths(
        self,
        library_id: int,
        policy: ReconcilePolicy = "mark_invalid",
        batch_size: int = 1000,
    ) -> ReconcileResult:
        """Re-validate all library paths against current configuration.

        This checks all files in the songs table to detect paths that have
        become invalid due to config changes (library root moves, deletions, etc.).
        Useful after modifying library configurations or recovering from filesystem changes.

        Args:
            library_id: Library document id to scope reconciliation to
            policy: What to do with invalid paths:
                - "dry_run": Only report, don't modify database
                - "mark_invalid": Keep files but log warnings (default)
                - "delete_invalid": Remove invalid files from database
            batch_size: Number of files to process per batch (default: 1000)

        Returns:
            Dict with reconciliation statistics:
                - total_files: Total files checked
                - valid_files: Files that passed validation
                - invalid_config: Files outside current library roots
                - not_found: Files that don't exist on disk
                - unknown_status: Files with other validation issues
                - deleted_files: Files removed (if policy="delete_invalid")
                - errors: Validation errors

        Raises:
            ValueError: If library_root not configured or invalid policy

        Example:
            # After changing library root configuration
            result = library_service.reconcile_library_paths(
                library_id=1,
                policy="delete_invalid",
                batch_size=500
            )
            print(f"Cleaned up {result['deleted_files']} invalid files")

        """
        return reconcile_library_paths_workflow(
            db=self.db,
            library_id=library_id,
            library_root=self.cfg.library_root,
            policy=policy,
            batch_size=batch_size,
        )

    def resolve_path_within_library(
        self,
        library_root: str,
        user_path: str,
        *,
        must_exist: bool = True,
        must_be_file: bool | None = None,
    ) -> Path:
        """Resolve and validate a user path within library boundaries.

        Args:
            library_root: Library root path
            user_path: User-provided path (absolute or relative)
            must_exist: Whether path must exist on filesystem
            must_be_file: If set, whether path must be a file (True) or directory (False)

        Returns:
            Resolved absolute path

        Raises:
            ValueError: If path is outside library_root or validation fails

        """
        return resolve_path_within_library(library_root, user_path, must_exist=must_exist, must_be_file=must_be_file)

    def retry_errored_songs(
        self,
        library_id: int,
        song_ids: list[int] | None = None,
    ) -> RetryErroredResult:
        """Clear errored state for songs and re-queue them for discovery.

        Args:
            library_id: Library ID to scope the operation
            song_ids: Optional subset of song IDs to retry. If None, retries all errored.

        Returns:
            RetryErroredResult with count of retried songs

        Raises:
            ValueError: If library does not exist

        """
        self._get_library_or_error(library_id)
        errored_ids = get_errored_song_ids(self.db, int(library_id))
        if song_ids:
            allowed = set(song_ids)
            errored_ids = [fid for fid in errored_ids if fid in allowed]
        if errored_ids:
            transition_song_state(self.db, errored_ids, STATE_ERRORED, STATE_NOT_ERRORED)
            transition_song_state(self.db, errored_ids, STATE_PROCESSED, STATE_NOT_PROCESSED)
        cleared = len(errored_ids)
        return RetryErroredResult(retried=cleared)
