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
from nomarr.components.library.library_file_query_comp import get_library_counts
from nomarr.components.library.library_records_comp import (
    get_library_record,
    list_library_records,
    update_library_config_fields,
)
from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp
from nomarr.components.platform.arango_bootstrap_comp import provision_vectors_track_for_library
from nomarr.helpers.config_schema import validate_library_config
from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.helpers.dto.vector_config_dto import VectorConfigResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService
    from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService

    from .config import LibraryServiceConfig


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    # Attributes provided by composed class (LibraryService)
    cfg: LibraryServiceConfig
    db: Database
    file_watcher_service: FileWatcherService | None

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
        result = get_library_record(self.db, library_id)
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
        library_auto_write: bool = False,
    ) -> LibraryDict:
        """Create a new library and provision vector collections for it.

        Creates the library record, then performs idempotent vector
        provisioning for the new library. Vector provisioning is skipped when
        no ML models are configured.

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
        library_key = library_id.split("/", 1)[-1]
        provision_vectors_track_for_library(self.db.db, self.cfg.models_dir, library_key)

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
        library_auto_write: bool | None = None,
    ) -> LibraryDict:
        """Update library properties.

        Args:
            library_id: Library document ``_id``.
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

        if root_path is not None:
            self.update_library_root(library_id, root_path)

        if (
            name is not None
            or is_enabled is not None
            or watch_mode is not None
            or file_write_mode is not None
            or library_auto_write is not None
        ):
            self.update_library_metadata(
                library_id,
                name=name,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
            )

        return self.get_library(library_id)

    def delete_library(self, library_id: str) -> bool:
        """Stop file watching for a library and delete it.

        Args:
            library_id: Library document ``_id`` to delete.

        Returns:
            True if the library was deleted, False if it was not found.
        """
        if self.file_watcher_service is not None and library_id in self.file_watcher_service.observers:
            self.file_watcher_service.stop_watching_library(library_id)
        return delete_library(db=self.db, library_id=library_id)

    def update_library_metadata(
        self,
        library_id: str,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> LibraryDict:
        """Update library metadata (name, enabled, watch_mode, file_write_mode)."""
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
            vector_group_size=global_group_size if lib.get("vector_group_size") is None else lib["vector_group_size"],
            vector_search_thoroughness=(
                global_thoroughness
                if lib.get("vector_search_thoroughness") is None
                else lib["vector_search_thoroughness"]
            ),
            is_group_size_inherited=lib.get("vector_group_size") is None,
            is_thoroughness_inherited=lib.get("vector_search_thoroughness") is None,
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

        update_library_config_fields(self.db, library_id, set_fields or None, unset_fields or None)
