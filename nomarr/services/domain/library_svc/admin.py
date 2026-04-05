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
    update_library_root,
)
from nomarr.helpers.config_schema import validate_library_config
from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.helpers.dto.vector_config_dto import VectorConfigResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService

    from .config import LibraryServiceConfig


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    # Attributes provided by composed class (LibraryService)
    cfg: LibraryServiceConfig
    db: Database

    def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
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
        result = self.db.libraries.get_library(library_id)
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
    ) -> LibraryDict:
        """Create a new library."""
        library_id = create_library(
            db=self.db,
            base_library_root=self.cfg.library_root,
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
        )

        library = self._get_library_or_error(library_id)
        return LibraryDict(**library)

    def update_library_root(self, library_id: str, root_path: str) -> LibraryDict:
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
                library_id,
                name=name,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
            )

        return self.get_library(library_id)

    def delete_library(self, library_id: str) -> bool:
        """Delete a library."""
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
        self._get_library_or_error(library_id)
        self.db.libraries.update_library(
            library_id,
            name=name,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
        )

        updated = self._get_library_or_error(library_id)
        return LibraryDict(**updated)

    def clear_library_data(self) -> None:
        """Clear all library data (files, tags, scan queue)."""
        clear_library_data(db=self.db, library_root=self.cfg.library_root)

    def get_vector_config(self, library_id: str, config_service: ConfigService) -> VectorConfigResult:
        """Resolve effective vector config for a library.

        Per-library overrides fall back to global defaults from DynamicConfig.

        Args:
            library_id: Library _id or _key
            config_service: ConfigService for global defaults

        Returns:
            VectorConfigResult with effective values and inheritance flags

        Raises:
            ValueError: If library not found

        """
        lib = self._get_library_or_error(library_id)
        global_group_size: int = config_service.get("vector_group_size", 15)
        global_thoroughness: int = config_service.get("vector_search_thoroughness", 10)
        return VectorConfigResult(
            vector_group_size=lib.get("vector_group_size", global_group_size),
            vector_search_thoroughness=lib.get("vector_search_thoroughness", global_thoroughness),
            is_group_size_inherited="vector_group_size" not in lib,
            is_thoroughness_inherited="vector_search_thoroughness" not in lib,
        )

    def update_vector_config(
        self,
        library_id: str,
        *,
        vector_group_size: int | None = None,
        vector_search_thoroughness: int | None = None,
    ) -> None:
        """Update per-library vector config fields.

        Non-None values are validated and persisted on the library document.
        None values clear the override so the library inherits the global default.

        Args:
            library_id: Library _id or _key
            vector_group_size: New group size (None to inherit global)
            vector_search_thoroughness: New thoroughness (None to inherit global)

        Raises:
            ValueError: If library not found or values out of range

        """
        self._get_library_or_error(library_id)
        set_fields: dict[str, Any] = {}
        unset_fields: list[str] = []

        if vector_group_size is not None:
            validate_library_config({"vector_group_size": vector_group_size})
            set_fields["vector_group_size"] = vector_group_size
        else:
            unset_fields.append("vector_group_size")

        if vector_search_thoroughness is not None:
            validate_library_config({"vector_search_thoroughness": vector_search_thoroughness})
            set_fields["vector_search_thoroughness"] = vector_search_thoroughness
        else:
            unset_fields.append("vector_search_thoroughness")

        self.db.libraries.update_library_config_fields(library_id, set_fields or None, unset_fields or None)
