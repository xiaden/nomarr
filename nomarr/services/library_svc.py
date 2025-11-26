"""
Library service.
Shared business logic for library management and scanning across all interfaces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.helpers.files_helper import resolve_library_path

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.workers.scanner import LibraryScanWorker


@dataclass
class LibraryRootConfig:
    """Configuration for LibraryService (library root management)."""

    namespace: str
    library_root: str | None


class LibraryService:
    """
    Library management and scanning operations - shared by all interfaces.

    This service manages libraries (user-defined scan roots under library_root)
    and coordinates scanning across CLI and API interfaces via the library_queue table.

    Note: Libraries only control which filesystem roots are scanned. All scan results,
    files, and tags remain global (not segmented by library).
    """

    def __init__(
        self,
        db: Database,
        cfg: LibraryRootConfig,
        worker: LibraryScanWorker | None = None,
    ):
        """
        Initialize library service.

        Args:
            db: Database instance
            cfg: Library root configuration (defines security boundary)
            worker: LibraryScanWorker instance (for background scans in API)
        """
        self.db = db
        self.cfg = cfg
        self.worker = worker

    def _get_library_root(self) -> Path:
        """
        Get the configured library_root (security boundary).

        This is the top-level directory that all library roots must be nested under.
        It comes from cfg.library_root and defines the security boundary for file access.

        Returns:
            Absolute Path to library_root directory

        Raises:
            ValueError: If library_root not configured or invalid
        """
        if not self.cfg.library_root:
            raise ValueError("Library root not configured")

        try:
            base = Path(self.cfg.library_root).expanduser().resolve()

            if not base.exists():
                raise ValueError(f"Base library root does not exist: {self.cfg.library_root}")
            if not base.is_dir():
                raise ValueError(f"Base library root is not a directory: {self.cfg.library_root}")

            return base

        except Exception as e:
            raise ValueError(f"Invalid base library root: {e}") from e

    def _normalize_library_root(self, raw_root: str | Path) -> str:
        """
        Normalize and validate a user-provided library root path.

        This ensures the library root:
        - Exists and is a directory
        - Is strictly within the configured base library_path
        - Is canonicalized to an absolute path

        Args:
            raw_root: User-provided library root (absolute or relative)

        Returns:
            Canonical absolute path string for storage in database

        Raises:
            ValueError: If path is invalid or outside base library root
        """
        import os

        # Get base root from config
        base_root = self._get_library_root()

        # Convert raw_root to string for processing
        raw_root_str = str(raw_root)

        # Determine if input is absolute or relative
        raw_path = Path(raw_root_str)

        if raw_path.is_absolute():
            # Convert absolute path to relative path from base root
            try:
                # Resolve to handle any symlinks/.. in the path
                abs_path = raw_path.resolve()
                # Get relative path from base root
                user_path = os.path.relpath(abs_path, base_root)
            except (ValueError, OSError) as e:
                # relpath can fail if paths are on different drives on Windows
                raise ValueError(f"Cannot compute relative path from base root: {e}") from e
        else:
            # Already relative, use as-is
            user_path = raw_root_str

        # Validate using resolve_library_path
        try:
            resolved = resolve_library_path(
                library_root=base_root,
                user_path=user_path,
                must_exist=True,
                must_be_file=False,
            )
        except ValueError as e:
            # Re-raise with more context
            raise ValueError(f"Library root validation failed: {e}") from e

        return str(resolved)

    def _ensure_no_overlapping_library_root(
        self,
        candidate_root: str,
        *,
        ignore_id: int | None = None,
    ) -> None:
        """
        Ensure a candidate library root does not overlap with existing libraries.

        This enforces the business rule that all library roots must be disjoint -
        no library may be nested inside another, and no two libraries may share
        overlapping directory trees.

        Args:
            candidate_root: Absolute path to validate
            ignore_id: Optional library ID to ignore (for updates)

        Raises:
            ValueError: If candidate_root overlaps with any existing library root
        """
        # Resolve candidate to canonical absolute path
        candidate_path = Path(candidate_root).resolve()

        # Fetch all existing libraries
        existing_libraries = self.db.libraries.list_libraries(enabled_only=False)

        for library in existing_libraries:
            # Skip if this is the library being updated
            if ignore_id is not None and library["id"] == ignore_id:
                continue

            # Resolve existing library root
            existing_path = Path(library["root_path"]).resolve()

            # Check if candidate is inside existing library
            try:
                candidate_path.relative_to(existing_path)
                # If no ValueError raised, candidate is inside existing
                raise ValueError(
                    f"Library root '{candidate_root}' is nested inside "
                    f"existing library '{library['name']}' at '{library['root_path']}'. "
                    f"Library roots must be disjoint."
                )
            except ValueError as e:
                # relative_to raises ValueError if not a subpath - this is expected for disjoint paths
                if "is nested inside" in str(e):
                    # Re-raise our custom error
                    raise
                # Otherwise, paths are not related - continue checking

            # Check if existing library is inside candidate
            try:
                existing_path.relative_to(candidate_path)
                # If no ValueError raised, existing is inside candidate
                raise ValueError(
                    f"Existing library '{library['name']}' at '{library['root_path']}' "
                    f"is nested inside new library root '{candidate_root}'. "
                    f"Library roots must be disjoint."
                )
            except ValueError as e:
                # relative_to raises ValueError if not a subpath - this is expected for disjoint paths
                if "is nested inside" in str(e):
                    # Re-raise our custom error
                    raise
                # Otherwise, paths are not related - continue checking

    def _resolve_path_within_library(
        self,
        library_root: str,
        user_path: str | Path,
        *,
        must_exist: bool = True,
        must_be_file: bool | None = None,
    ) -> Path:
        """
        Resolve a user-provided path within a library root.

        This is a thin wrapper around helpers.files.resolve_library_path
        for use within LibraryService methods that need to validate paths
        within a library (e.g., scanning subdirectories, loading specific files).

        DO NOT use this for validating library roots themselves - use Path().resolve()
        directly for that, since there's no parent root to validate against yet.

        Args:
            library_root: Absolute path to library root directory
            user_path: User-provided path (relative or absolute) to resolve
            must_exist: If True, require path to exist (default: True)
            must_be_file: If True, require file; if False, require directory; if None, allow either

        Returns:
            Resolved absolute Path within library root

        Raises:
            ValueError: If path validation fails
        """
        return resolve_library_path(
            library_root=library_root,
            user_path=user_path,
            must_exist=must_exist,
            must_be_file=must_be_file,
        )

    def _get_library_or_error(self, library_id: int) -> dict[str, Any]:
        """
        Get a library by ID or raise an error.

        Libraries are used only to determine scan roots. This method retrieves
        library metadata (name, root_path, enabled status) but does NOT propagate
        library_id to scanning workflows or persistence operations.

        Args:
            library_id: ID of the library to retrieve

        Returns:
            Library dict with keys: id, name, root_path, is_enabled, is_default, etc.

        Raises:
            ValueError: If library does not exist
        """
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return library

    def _get_default_library_or_error(self) -> dict[str, Any]:
        """
        Get the default library, creating it if necessary.

        Libraries control which filesystem roots are scanned. This method ensures
        a default library exists (creating one from library_root config if needed)
        but does NOT propagate library_id beyond determining the scan root.

        Returns:
            Default library dict with keys: id, name, root_path, is_enabled, is_default, etc.

        Raises:
            ValueError: If no default library exists and cannot be created
        """
        library = self.db.libraries.get_default_library()
        if library:
            return library

        # No default exists - try to create one
        logging.info("[LibraryService] No default library found, attempting to create one")
        self.ensure_default_library_exists()

        # Reload default after creation
        library = self.db.libraries.get_default_library()
        if not library:
            raise ValueError("Failed to create or locate default library")

        return library

    def is_library_root_configured(self) -> bool:
        """
        Check if library_root is configured.

        Returns:
            True if library_root is set in config
        """
        return self.cfg.library_root is not None

    def start_scan_for_library(
        self,
        library_id: int,
        paths: list[str] | None = None,
        recursive: bool = True,
        force: bool = False,
        clean_missing: bool = True,
    ) -> dict[str, Any]:
        """
        Start a library scan for a specific library.

        IMPORTANT: Libraries are used ONLY to determine which filesystem roots to scan.
        All discovered files, queue entries, and statistics remain GLOBAL and do NOT track
        library_id. Nomarr is an autotagger, not a multi-tenant library manager.

        This method:
        1. Resolves the library to get its root_path
        2. Validates any user-provided paths are within that root
        3. Calls the global scanning workflow with root_paths
        4. All discovered files are added to global library_files table (no library_id column)

        Args:
            library_id: ID of the library to scan (used only to determine scan root)
            paths: Optional list of paths within the library to scan (defaults to library root)
            recursive: Whether to scan subdirectories recursively
            force: Whether to force rescan even if files haven't changed
            clean_missing: Whether to remove deleted files from database

        Returns:
            Dict with scan statistics from start_library_scan_workflow

        Raises:
            ValueError: If library not found or paths are invalid
        """
        # Fetch library - this is used ONLY to determine the root_path to scan.
        # The library_id is NOT propagated to workflows or persistence layers.
        library = self._get_library_or_error(library_id)
        base_root = Path(library["root_path"])

        # Build root_paths for scanning.
        # Libraries control which roots to scan, but the workflow operates globally.
        if paths is None:
            # Scan entire library root
            root_paths = [str(base_root)]
        else:
            # Validate each user path is within library root
            root_paths = []
            for user_path in paths:
                resolved = self._resolve_path_within_library(
                    library_root=str(base_root),
                    user_path=user_path,
                    must_exist=True,
                    must_be_file=False,
                )
                root_paths.append(str(resolved))

        from nomarr.workflows.library.start_library_scan_wf import start_library_scan_workflow

        logging.info(
            f"[LibraryService] Starting scan for library {library_id} "
            f"({library['name']}) with {len(root_paths)} path(s)"
        )

        # Call the global scanning workflow.
        # NOTE: library_id is NOT passed to the workflow - it only receives root_paths.
        # All discovered files are added to global library_files table without library_id.
        stats = start_library_scan_workflow(
            db=self.db,
            root_paths=root_paths,
            recursive=recursive,
            force=force,
            auto_tag=False,  # Auto-tagging is handled by LibraryScanWorker per file
            ignore_patterns="",
            clean_missing=clean_missing,
        )

        logging.info(
            f"[LibraryService] Scan planned for library {library_id}: "
            f"discovered={stats['files_discovered']}, queued={stats['files_queued']}, "
            f"skipped={stats['files_skipped']}, removed={stats['files_removed']}"
        )

        # TypedDict is compatible with dict[str, Any] at runtime
        return dict(stats)  # type: ignore[return-value]

    def start_scan(
        self,
        library_id: int | None = None,
        paths: list[str] | None = None,
        recursive: bool = True,
        force: bool = False,
        clean_missing: bool = True,
    ) -> dict[str, Any]:
        """
        Start a library scan.

        This is the main scanning entrypoint. It resolves a library (either specified
        or default) and delegates to start_scan_for_library.

        IMPORTANT: Libraries are used ONLY to pick which filesystem roots to scan.
        All discovered files and stats are GLOBAL and do NOT carry library_id.
        The library_files, library_queue, and stats tables remain unaware of libraries.

        Args:
            library_id: ID of library to scan (defaults to default library)
            paths: List of paths to scan within the library (defaults to library root)
            recursive: Whether to scan subdirectories recursively
            force: Whether to force rescan even if files haven't changed
            clean_missing: Whether to remove deleted files from database

        Returns:
            Dict with scan statistics from start_library_scan_workflow

        Raises:
            ValueError: If library not found or no default library exists
        """
        # Resolve library_id
        if library_id is not None:
            # Use explicitly provided library
            return self.start_scan_for_library(
                library_id=library_id,
                paths=paths,
                recursive=recursive,
                force=force,
                clean_missing=clean_missing,
            )
        else:
            # Use default library
            default_library = self._get_default_library_or_error()
            return self.start_scan_for_library(
                library_id=default_library["id"],
                paths=paths,
                recursive=recursive,
                force=force,
                clean_missing=clean_missing,
            )

    def cancel_scan(self) -> bool:
        """
        Cancel the currently running scan.

        Note: With per-file scanning, this clears the pending queue.
        Files currently being processed will complete.

        Returns:
            Number of pending jobs cancelled

        Raises:
            ValueError: If library not configured
        """
        if not self.cfg.library_root:
            raise ValueError("Library scanning not configured")

        # Clear pending scan jobs from queue
        cleared = self.db.library_queue.clear_scan_queue()
        logging.info(f"[LibraryService] Cleared {cleared} pending scan jobs")
        return cleared > 0

    def get_status(self) -> dict[str, Any]:
        """
        Get current library scan status.

        Returns:
            Dict with:
                - configured: bool
                - library_path: str | None
                - enabled: bool (worker running)
                - pending_jobs: int (files waiting to be scanned)
                - running_jobs: int (files currently being scanned)
        """
        if not self.cfg.library_root:
            return {
                "configured": False,
                "library_path": None,
                "enabled": False,
                "pending_jobs": 0,
                "running_jobs": 0,
            }

        # Check if worker is available
        enabled = self.worker is not None

        # Count jobs by status
        pending_jobs = self.db.library_queue.count_pending_scans()
        jobs = self.db.library_queue.list_scan_jobs(limit=1000)
        running_jobs = sum(1 for job in jobs if job["status"] == "running")

        return {
            "configured": True,
            "library_path": self.cfg.library_root,
            "enabled": enabled,
            "pending_jobs": pending_jobs,
            "running_jobs": running_jobs,
        }

    def get_scan_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get recent library scan jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts with id, path, status, started_at, completed_at, etc.
        """
        return self.db.library_queue.list_scan_jobs(limit=limit)

    def get_library_stats(self) -> dict[str, Any]:
        """
        Get library statistics (total files, total duration, etc.).

        Returns:
            Dictionary with library statistics
        """
        return self.db.library_files.get_library_stats()

    def get_all_library_paths(self) -> list[str]:
        """
        Get all file paths in the library.

        Returns:
            List of absolute file paths
        """
        return self.db.library_files.get_all_library_paths()

    def _is_scan_running(self) -> bool:
        """
        Check if any scan jobs are currently being processed.

        Returns:
            True if any jobs are in 'running' status
        """
        # Query for any running scan jobs
        jobs = self.db.library_queue.list_scan_jobs(limit=1000)
        return any(job["status"] == "running" for job in jobs)

    def pause(self) -> bool:
        """
        Pause the library scanner worker.

        Returns:
            True if paused successfully

        Raises:
            ValueError: If library_root not configured
        """
        if not self.cfg.library_root:
            raise ValueError("Library root not configured")

        # Set scan_running=false in database meta
        self.db.meta.set("worker_enabled", "false")
        logging.info("[LibraryService] Library scanner paused via worker_enabled flag")
        return True

    def resume(self) -> bool:
        """
        Resume the library scanner worker.

        Returns:
            True if resumed successfully

        Raises:
            ValueError: If library_root not configured
        """
        if not self.cfg.library_root:
            raise ValueError("Library root not configured")

        # Set worker_enabled=true in database meta
        self.db.meta.set("worker_enabled", "true")
        logging.info("[LibraryService] Library scanner resumed via worker_enabled flag")
        return True

    def clear_library_data(self) -> None:
        """
        Clear all library data (files, tags, scan queue).

        This forces a fresh rescan by removing all existing library state.
        Does not affect the ML tagging queue or system metadata.

        Raises:
            ValueError: If library_root not configured
            RuntimeError: If scan jobs are currently running
        """
        if not self.cfg.library_root:
            raise ValueError("Library root not configured")

        # Check if any jobs are running
        if self._is_scan_running():
            raise RuntimeError("Cannot clear library while scan jobs are running. Cancel scans first.")

        self.db.library_files.clear_library_data()
        logging.info("[LibraryService] Library data cleared")

    # ------------------------------------------------------------------
    # Library Management (CRUD)
    # ------------------------------------------------------------------
    # Libraries exist ONLY to control which filesystem roots are scanned.
    # They do NOT segment library_files, library_queue, or stats.
    # All scan results remain global across all libraries.
    # ------------------------------------------------------------------

    def list_libraries(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """
        List all configured libraries.

        Args:
            enabled_only: Only return enabled libraries

        Returns:
            List of Library dicts
        """
        return self.db.libraries.list_libraries(enabled_only=enabled_only)

    def get_library(self, library_id: int) -> dict[str, Any]:
        """
        Get a library by ID.

        Args:
            library_id: Library ID

        Returns:
            Library dict

        Raises:
            ValueError: If library not found
        """
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return library

    def get_default_library(self) -> dict[str, Any] | None:
        """
        Get the default library.

        Returns:
            Default Library dict or None if no default set
        """
        return self.db.libraries.get_default_library()

    def create_library(
        self,
        name: str,
        root_path: str,
        is_enabled: bool = True,
        is_default: bool = False,
    ) -> dict[str, Any]:
        """
        Create a new library.

        Libraries define which filesystem roots can be scanned. They do NOT segment
        library data - all files discovered from any library are added to the global
        library_files table without library_id tracking.

        Args:
            name: Library name (must be unique)
            root_path: Absolute path to library root (must be within configured library_root)
            is_enabled: Whether library is enabled for scanning
            is_default: Whether this is the default library

        Returns:
            Created library dict

        Raises:
            ValueError: If name already exists or path is invalid
        """
        # Validate and normalize path (must be within base library_path)
        abs_path = self._normalize_library_root(root_path)

        # Ensure no overlapping library roots
        self._ensure_no_overlapping_library_root(abs_path, ignore_id=None)

        # Check for duplicate name
        existing = self.db.libraries.get_library_by_name(name)
        if existing:
            raise ValueError(f"Library name already exists: {name}")

        # Create library
        try:
            library_id = self.db.libraries.create_library(
                name=name,
                root_path=abs_path,
                is_enabled=is_enabled,
                is_default=is_default,
            )
        except Exception as e:
            raise ValueError(f"Failed to create library: {e}") from e

        logging.info(f"[LibraryService] Created library: {name} at {abs_path}")

        # Return the created library
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise RuntimeError("Failed to retrieve created library")
        return library

    def update_library_root(self, library_id: int, root_path: str) -> dict[str, Any]:
        """
        Update a library's root path.

        Args:
            library_id: Library ID
            root_path: New absolute path to library root

        Returns:
            Updated Library dict

        Raises:
            ValueError: If library not found or path is invalid
        """
        # Check library exists
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")

        # Validate and normalize path (must be within base library_path)
        abs_path = self._normalize_library_root(root_path)

        # Ensure no overlapping library roots (ignore current library being updated)
        self._ensure_no_overlapping_library_root(abs_path, ignore_id=library_id)

        # Update library
        success = self.db.libraries.update_library(library_id, root_path=abs_path)
        if not success:
            raise ValueError(f"Failed to update library: {library_id}")

        logging.info(f"[LibraryService] Updated library {library_id} root path to {abs_path}")

        # Return Updated library
        updated = self.db.libraries.get_library(library_id)
        if not updated:
            raise RuntimeError("Failed to retrieve Updated library")
        return updated

    def set_default_library(self, library_id: int) -> dict[str, Any]:
        """
        Set a library as the default.

        Args:
            library_id: Library ID

        Returns:
            Updated Library dict

        Raises:
            ValueError: If library not found
        """
        success = self.db.libraries.set_default_library(library_id)
        if not success:
            raise ValueError(f"Library not found: {library_id}")

        logging.info(f"[LibraryService] Set library {library_id} as default")

        # Return updated library
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise RuntimeError("Failed to retrieve updated library")
        return library

    def update_library_metadata(
        self,
        library_id: int,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """
        Update name and/or enabled status of a library.

        Root path updates are handled separately by update_library_root.
        Default flag updates are handled by set_default_library.

        Args:
            library_id: Library ID
            name: New name (optional)
            is_enabled: New enabled state (optional)

        Returns:
            Updated library dict

        Raises:
            ValueError: If library not found or name conflicts
        """
        # Validate library exists (raises ValueError if not found)
        _ = self.get_library(library_id)

        # Update via persistence layer
        success = self.db.libraries.update_library(
            library_id,
            name=name,
            is_enabled=is_enabled,
        )
        if not success:
            raise ValueError(f"Failed to update library: {library_id}")

        logging.info(f"[LibraryService] Updated library {library_id} metadata")

        # Return updated library
        updated = self.db.libraries.get_library(library_id)
        if not updated:
            raise RuntimeError("Failed to retrieve updated library")
        return updated

    def ensure_default_library_exists(self) -> None:
        """
        Ensure at least one library exists, creating a default from config if needed.

        This should be called on service initialization to migrate from single
        library_path config to multi-library model.
        """
        # Check if any libraries exist
        count = self.db.libraries.count_libraries()
        if count > 0:
            return

        # No libraries exist - create default from config
        try:
            base = self._get_library_root()
            root_path = str(base)
        except ValueError as e:
            logging.warning(f"[LibraryService] Cannot create default library: {e}")
            return

        # Create default library using the base root
        try:
            library_id = self.db.libraries.create_library(
                name="Default Library",
                root_path=root_path,
                is_enabled=True,
                is_default=True,
            )
            logging.info(f"[LibraryService] Created default library (ID {library_id}) from config: {root_path}")
        except Exception as e:
            logging.error(f"[LibraryService] Failed to create default library: {e}")
