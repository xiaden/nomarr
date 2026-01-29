"""Library administration - CRUD operations for library management.

This module handles:
- Library configuration checks
- Library CRUD (create, read, update, delete)
- Clearing library data
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.library_dto import LibraryDict

if TYPE_CHECKING:
    from nomarr.components.library.get_library_comp import GetLibraryComp
    from nomarr.components.library.get_library_counts_comp import GetLibraryCountsComp
    from nomarr.components.library.list_libraries_comp import ListLibrariesComp
    from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp

    from .config import LibraryServiceConfig


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    # Component dependencies
    get_library: GetLibraryComp
    list_libraries: ListLibrariesComp
    get_library_counts: GetLibraryCountsComp
    update_library_metadata: UpdateLibraryMetadataComp
    cfg: LibraryServiceConfig

    def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
        """
        Get a library by ID or raise an error.

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
        return self.get_library.get_or_error(library_id)

    def is_library_root_configured(self) -> bool:
        """
        Check if library_root is configured.

        Returns:
            True if library_root is set in config
        """
        return self.cfg.library_root is not None

    def list_libraries(self, enabled_only: bool = False) -> list[LibraryDict]:
        """
        List all configured libraries.

        Args:
            enabled_only: Only return enabled libraries

        Returns:
            List of LibraryDict DTOs with file/folder counts
        """
        libraries = self.list_libraries.list(enabled_only=enabled_only)

        # Get file/folder counts for all libraries
        counts = self.get_library_counts.get()

        result = []
        for lib in libraries:
            lib_dto = LibraryDict(**lib)
            # Augment with counts (default to 0 if not in counts dict)
            lib_counts = counts.get(lib_dto._id, {"file_count": 0, "folder_count": 0})
            lib_dto.file_count = lib_counts["file_count"]
            lib_dto.folder_count = lib_counts["folder_count"]
            result.append(lib_dto)

        return result

    def get_library(self, library_id: str) -> LibraryDict:
        """
        Get a library by ID.

        Args:
            library_id: Library ID

        Returns:
            LibraryDict DTO

        Raises:
            ValueError: If library not found
        """
        library = self.get_library.get_or_error(library_id)
        return LibraryDict(**library)

    def create_library(
        self, name: str | None, root_path: str, is_enabled: bool = True, watch_mode: str = "off"
    ) -> LibraryDict:
        """Create a new library."""
        from nomarr.components.library.library_admin_comp import create_library

        library_id = create_library(
            db=self.db,
            base_library_root=self.cfg.library_root,
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
        )

        library = self.get_library.get_or_error(library_id)
        return LibraryDict(**library)

    def update_library_root(self, library_id: str, root_path: str) -> LibraryDict:
        """Update a library's root path."""
        from nomarr.components.library.library_admin_comp import update_library_root

        update_library_root(
            db=self.db, base_library_root=self.cfg.library_root, library_id=library_id, root_path=root_path
        )

        from nomarr.components.library.get_library_comp import get_library_or_error

        updated = get_library_or_error(self.db, library_id)
        return LibraryDict(**updated)

    def update_library(
        self,
        library_id: str,
        *,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
    ) -> LibraryDict:
        """Update library properties."""
        # Validate library exists
        self._get_library_or_error(library_id)

        if root_path is not None:
            self.update_library_root(library_id, root_path)

        if name is not None or is_enabled is not None or watch_mode is not None or file_write_mode is not None:
            self.update_library_metadata(
                library_id, name=name, is_enabled=is_enabled, watch_mode=watch_mode, file_write_mode=file_write_mode
            )

        return self.get_library(library_id)

    def delete_library(self, library_id: str) -> bool:
        """Delete a library."""
        from nomarr.components.library.library_admin_comp import delete_library

        return delete_library(db=self.db, library_id=library_id)

    def update_library_metadata(
        self,
        library_id: str,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
    ) -> LibraryDict:
        """Update library metadata (name, enabled, watch_mode, file_write_mode)."""
        from nomarr.components.library.get_library_comp import get_library_or_error
        from nomarr.components.library.update_library_metadata_comp import update_library_metadata

        self._get_library_or_error(library_id)
        update_library_metadata(
            self.db,
            library_id,
            name=name,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
        )

        updated = get_library_or_error(self.db, library_id)
        return LibraryDict(**updated)

    def clear_library_data(self) -> None:
        """Clear all library data (files, tags, scan queue)."""
        from nomarr.components.library.library_admin_comp import clear_library_data

        clear_library_data(db=self.db, library_root=self.cfg.library_root)
