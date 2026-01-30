"""Library file operations.

This module handles:
- Cleaning up orphaned tags in DB
- Path reconciliation and validation
- File tag queries from DB
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.file_tags_comp import get_file_tags_with_path
from nomarr.components.library.library_root_comp import resolve_path_within_library
from nomarr.helpers.dto.library_dto import FileTag, FileTagsResult, TagCleanupResult
from nomarr.workflows.library.cleanup_orphaned_tags_wf import cleanup_orphaned_tags_workflow
from nomarr.workflows.library.reconcile_paths_wf import reconcile_library_paths_workflow

if TYPE_CHECKING:
    from pathlib import Path

    from nomarr.components.library.reconcile_paths_comp import ReconcileResult
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryFilesMixin:
    """Mixin providing library file operations."""

    db: Database
    cfg: LibraryServiceConfig

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

    def get_file_tags(self, file_id: str, nomarr_only: bool = False) -> FileTagsResult:
        """Get all tags for a specific file.

        Args:
            file_id: Library file ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            FileTagsResult DTO with file info and tags

        Raises:
            ValueError: If file not found

        """
        # Get file and tags from component
        result = get_file_tags_with_path(self.db, file_id, nomarr_only=nomarr_only)
        if not result:
            msg = f"File with ID {file_id} not found"
            raise ValueError(msg)

        # Convert to FileTag DTOs
        tags = [
            FileTag(
                key=tag["key"],
                value=str(tag["value"]),
                tag_type=tag["type"],
                is_nomarr=tag["is_nomarr_tag"],
            )
            for tag in result["tags"]
        ]

        return FileTagsResult(
            file_id=file_id,
            path=result["path"],
            tags=tags,
        )

    def reconcile_library_paths(
        self,
        policy: str = "mark_invalid",
        batch_size: int = 1000,
    ) -> ReconcileResult:
        """Re-validate all library paths against current configuration.

        This checks all files in library_files table to detect paths that have
        become invalid due to config changes (library root moves, deletions, etc.).
        Useful after modifying library configurations or recovering from filesystem changes.

        Args:
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
                policy="delete_invalid",
                batch_size=500
            )
            print(f"Cleaned up {result['deleted_files']} invalid files")

        """
        return reconcile_library_paths_workflow(
            db=self.db,
            library_root=self.cfg.library_root,
            policy=policy,  # type: ignore[arg-type]
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
