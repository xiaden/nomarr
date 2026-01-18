"""Library administration - CRUD operations for library management.

This module handles:
- Library configuration checks
- Library CRUD (create, read, update, delete)
- Default library management
- Clearing library data
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.library_dto import LibraryDict

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    db: Database
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
            Library dict with keys: id, name, root_path, is_enabled, is_default, etc.

        Raises:
            ValueError: If library does not exist
        """
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return library

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
        libraries = self.db.libraries.list_libraries(enabled_only=enabled_only)

        # Get file/folder counts for all libraries
        counts = self.db.library_files.get_library_counts()

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
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library not found: {library_id}")
        return LibraryDict(**library)

    def get_default_library(self) -> LibraryDict | None:
        """
        Get the default library.

        Returns:
            LibraryDict DTO or None if no default set
        """
        library_dict = self.db.libraries.get_default_library()
        if not library_dict:
            return None

        return LibraryDict(**library_dict)

    def create_library(
        self,
        name: str | None,
        root_path: str,
        is_enabled: bool = True,
        is_default: bool = False,
        watch_mode: str = "off",
    ) -> LibraryDict:
        """Create a new library."""
        from nomarr.components.library.library_admin_comp import create_library

        library_id = create_library(
            db=self.db,
            base_library_root=self.cfg.library_root,
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            is_default=is_default,
            watch_mode=watch_mode,
        )

        library = self.db.libraries.get_library(library_id)
        if not library:
            raise RuntimeError("Failed to retrieve created library")
        return LibraryDict(**library)

    def update_library_root(self, library_id: str, root_path: str) -> LibraryDict:
        """Update a library's root path."""
        from nomarr.components.library.library_admin_comp import update_library_root

        update_library_root(
            db=self.db,
            base_library_root=self.cfg.library_root,
            library_id=library_id,
            root_path=root_path,
        )

        updated = self.db.libraries.get_library(library_id)
        if not updated:
            raise RuntimeError("Failed to retrieve updated library")
        return LibraryDict(**updated)

    def update_library(
        self,
        library_id: str,
        *,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        is_default: bool | None = None,
        watch_mode: str | None = None,
    ) -> LibraryDict:
        """Update library properties."""
        # Validate library exists
        self._get_library_or_error(library_id)

        if root_path is not None:
            self.update_library_root(library_id, root_path)

        if is_default is True:
            self.set_default_library(library_id)

        if name is not None or is_enabled is not None or watch_mode is not None:
            self.update_library_metadata(library_id, name=name, is_enabled=is_enabled, watch_mode=watch_mode)

        return self.get_library(library_id)

    def set_default_library(self, library_id: str) -> LibraryDict:
        """Set a library as the default."""
        self._get_library_or_error(library_id)
        self.db.libraries.update_library(library_id, is_default=True)

        updated = self.db.libraries.get_library(library_id)
        if not updated:
            raise RuntimeError("Failed to retrieve updated library")
        return LibraryDict(**updated)

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
    ) -> LibraryDict:
        """Update library metadata (name, enabled, watch_mode)."""
        self._get_library_or_error(library_id)
        self.db.libraries.update_library(library_id, name=name, is_enabled=is_enabled, watch_mode=watch_mode)

        updated = self.db.libraries.get_library(library_id)
        if not updated:
            raise RuntimeError("Failed to retrieve updated library")
        return LibraryDict(**updated)

    def ensure_default_library_exists(self) -> None:
        """
        Placeholder for backward compatibility.

        Previously auto-created a default library from library_root config.
        Now does nothing - users should explicitly create libraries via Web UI.

        The library_root config is a SECURITY BOUNDARY (allowed path prefix),
        not a library itself. Libraries are subdirectories under library_root.
        """
        # No-op: Libraries should be created explicitly by users via Web UI
        # The old behavior of creating a library at the root security boundary was wrong
        pass

    def clear_library_data(self) -> None:
        """Clear all library data (files, tags, scan queue)."""
        from nomarr.components.library.library_admin_comp import clear_library_data

        clear_library_data(db=self.db, library_root=self.cfg.library_root)
