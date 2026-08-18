"""Library administration - CRUD operations for library management.

This module handles:
- Library configuration checks
- Library CRUD (create, read, update, delete)
- Clearing library data
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_admin_comp import (
    clear_library_data,
    create_library,
    delete_library,
    resolve_library_root,
    update_library_root,
)
from nomarr.components.library.library_records_comp import (
    get_library_record,
    list_library_records,
    update_library_record,
)
from nomarr.components.library.library_song_query_comp import get_library_counts
from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp
from nomarr.helpers.dto.library_dto import LibraryDict

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService

    from .config import LibraryServiceConfig


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    # Attributes provided by composed class (LibraryService)
    cfg: LibraryServiceConfig
    db: Database
    file_watcher_service: FileWatcherService | None

    def _get_library_or_error(self, library_id: int) -> dict[str, Any]:
        """Get a library by ID or raise an error.

        Libraries are used only to determine scan roots. This method retrieves
        library metadata (name, root_path, enabled status) but does NOT propagate
        library_id to scanning workflows or persistence operations.

        Args:
            library_id: ID of the library to retrieve

        Returns:
            Library dict with keys: id, name, root_path, is_enabled, etc.

        Raises:
            ValueError: If library does not exist

        """
        result = get_library_record(self.db, int(library_id))
        if result is None:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)
        return result

    def is_library_root_configured(self) -> bool:
        """Check if library_root is configured.

        Returns:
            True if library_root is set in config

        """
        return self.cfg.library_root is not None

    def list_libraries(self, enabled_only: bool = False) -> list[LibraryDict]:
        """List all configured libraries.

        Args:
            enabled_only: Only return enabled libraries

        Returns:
            List of LibraryDict DTOs with file/folder counts

        """
        libraries = list_library_records(self.db, enabled_only=enabled_only)

        # Get file/folder counts for all libraries
        counts = get_library_counts(self.db)

        result = []
        for lib in libraries:
            # Augment with counts (default to 0 if not in counts dict)
            lib_counts = counts.get(lib.id, {"file_count": 0, "folder_count": 0})
            lib.file_count = lib_counts["file_count"]
            lib.folder_count = lib_counts["folder_count"]
            result.append(lib)

        return result

    def get_library(self, library_id: int) -> LibraryDict:
        """Get a library by ID.

        Args:
            library_id: Library ID

        Returns:
            LibraryDict DTO

        Raises:
            ValueError: If library not found

        """
        library = self._get_library_or_error(library_id)
        return LibraryDict(**library)

    def create_library(
        self,
        name: str | None,
        root_path: str,
        is_enabled: bool = True,
        watch_mode: str = "off",
        file_write_mode: str = "full",
        library_auto_write: bool = False,
    ) -> LibraryDict:
        """Create a new library record.

        Creates the library record. Per-backbone vector collections are
        created once during schema setup (not per-library), so no vector
        provisioning is needed here.

        Args:
            name: Optional display name for the library.
            root_path: Filesystem root path for the library.
            is_enabled: Whether the library starts enabled.
            watch_mode: Watch mode to store on the library.
            file_write_mode: File write mode to store on the library.
            library_auto_write: Whether to enable automatic tag writing for the library.

        Returns:
            LibraryDict DTO for the created library record.

        """
        library_id = create_library(
            db=self.db,
            base_library_root=self.cfg.library_root,
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )

        library = self._get_library_or_error(library_id)
        return LibraryDict(**library)

    def update_library_root(self, library_id: int, root_path: str) -> LibraryDict:
        """Update a library's root path."""
        update_library_root(
            db=self.db,
            base_library_root=self.cfg.library_root,
            library_id=library_id,
            root_path=root_path,
        )
        updated = self._get_library_or_error(library_id)
        return LibraryDict(**updated)

    def update_library(
        self,
        library_id: int,
        *,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> LibraryDict:
        """Update library properties.

        Args:
            library_id: Library database ID.
            name: New display name (optional).
            root_path: New filesystem root path (optional).
            is_enabled: New enabled state (optional).
            watch_mode: New watch mode ('off', 'event', or 'poll') (optional).
            file_write_mode: New tag write mode ('none', 'minimal', or 'full') (optional).
            library_auto_write: New auto-write setting (optional).

        Returns:
            Updated LibraryDict DTO.

        """
        # Validate library exists
        self._get_library_or_error(library_id)

        normalized_root_path = None
        if root_path is not None:
            normalized_root_path = resolve_library_root(self.db, self.cfg.library_root, library_id, root_path)

        if (
            normalized_root_path is not None
            or name is not None
            or is_enabled is not None
            or watch_mode is not None
            or file_write_mode is not None
            or library_auto_write is not None
        ):
            update_library_record(
                self.db,
                library_id,
                name=name,
                root_path=normalized_root_path,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
            )

        return self.get_library(library_id)

    def delete_library(self, library_id: int) -> bool:
        """Stop file watching for a library and delete it.

        Args:
            library_id: Library database ID to delete.

        Returns:
            True if the library was deleted, False if it was not found.

        """
        if self.file_watcher_service is not None and str(library_id) in self.file_watcher_service.observers:
            self.file_watcher_service.stop_watching_library(str(library_id))
        return delete_library(db=self.db, library_id=int(library_id))

    def update_library_metadata(
        self,
        library_id: int,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> LibraryDict:
        """Update library metadata fields.

        Only the provided keyword arguments are updated; omitted fields are
        left unchanged. Delegates to the ``UpdateLibraryMetadataComp``
        component for persistence.

        Args:
            library_id: Library database ID to update.
            name: Optional new display name for the library.
            is_enabled: Optionally enable or disable the library.
            watch_mode: Optional watch mode (e.g. ``"polling"``, ``"inotify"``).
            file_write_mode: Optional file write mode (``"none"``, ``"minimal"``, ``"full"``).
            library_auto_write: When True, tags are written automatically after
                ML processing completes.

        Returns:
            Updated LibraryDict with the current library state.

        Raises:
            ValueError: If the library does not exist.

        """
        self._get_library_or_error(library_id)
        UpdateLibraryMetadataComp(self.db).update(
            library_id,
            name=name,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )

        updated = self._get_library_or_error(library_id)
        return LibraryDict(**updated)

    def clear_library_data(self) -> None:
        """Clear all library data (files, tags, scan queue).

        Wipes all library files, tags, edges, vectors, scan records, and
        pipeline states from the database. Requires no scans to be running.
        Intended for use when a full re-import is needed.

        Raises:
            RuntimeError: If a library scan is currently running.

        """
        clear_library_data(db=self.db, library_root=self.cfg.library_root)
