"""Library administration - CRUD operations for library management.

This module handles:
- Library configuration checks
- Library CRUD (create, read, update, delete)
- Clearing library data
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_admin_comp import (
    clear_library_data,
    create_library,
    delete_library,
    resolve_library_root,
    update_library_root,
)
from nomarr.components.library.library_records_comp import (
    get_library_by_name as component_get_library_by_name,
)
from nomarr.components.library.library_records_comp import (
    get_library_record,
    list_all_libraries,
    update_library_record,
)
from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp

from .task_ids import library_task_id, write_tags_task_id

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
    from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService

    from .config import LibraryServiceConfig


# Maximum seconds to wait for library-scoped background tasks (scan, tag-write)
# to quiesce before rejecting deletion.
_QUIESCE_TIMEOUT_SECONDS = 60.0


class LibraryAdminMixin:
    """Mixin providing library administration methods."""

    # Attributes provided by composed class (LibraryService)
    cfg: LibraryServiceConfig
    db: Database
    file_watcher_service: FileWatcherService | None
    background_tasks: BackgroundTaskService | None

    def get_library_by_name(self, name: str) -> Library | None:
        """Resolve a library by its natural name.

        This is the ONLY name resolver above persistence. It delegates to the
        natural-name component (``library_records_comp.get_library_by_name``).
        The interface adapter (P4-S8) resolves a decoded wire name exactly once
        via this method before invoking any other service method; services never
        perform wire-ID decoding or an integer-to-library lookup.

        Args:
            name: Natural library name.

        Returns:
            The matching domain ``Library``, or ``None`` when no such library exists.

        """
        return component_get_library_by_name(self.db, name)

    def _get_library_or_error(self, library: Library) -> Library:
        """Re-fetch a library by its natural identity or raise an error.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            The persisted domain ``Library`` value.

        Raises:
            ValueError: If the library does not exist.

        """
        result = get_library_record(self.db, library)
        if result is None:
            msg = f"Library not found: {library.name}"
            raise ValueError(msg)
        return result

    def is_library_root_configured(self) -> bool:
        """Check if library_root is configured.

        Returns:
            True if library_root is set in config

        """
        return self.cfg.library_root is not None

    def list_libraries(self, enabled_only: bool = False) -> list[Library]:
        """List all configured libraries as domain ``Library`` values.

        Args:
            enabled_only: Only return enabled libraries.

        Returns:
            List of domain ``Library`` values. Transport projections are built
            by the interface adapter (P4-S8); per-library file/folder counts are
            exposed via ``LibraryService.get_library_counts`` (mechanism A).
            Services no longer construct ``LibraryDict`` or expose generated ids.

        """
        libraries = list_all_libraries(self.db)
        if enabled_only:
            libraries = [lib for lib in libraries if lib.is_enabled]
        return libraries

    def get_library(self, library: Library) -> Library:
        """Get a library by its natural identity.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            The persisted domain ``Library`` value.

        Raises:
            ValueError: If library not found.

        """
        return self._get_library_or_error(library)

    def create_library(
        self,
        name: str | None,
        root_path: str,
        is_enabled: bool = True,
        watch_mode: str = "off",
        file_write_mode: str = "full",
        library_auto_write: bool = False,
    ) -> Library:
        """Create a new library record and return the domain ``Library``.

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
            The persisted domain ``Library`` value for the created library.

        """
        return create_library(
            db=self.db,
            base_library_root=self.cfg.library_root,
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )

    def update_library_root(self, library: Library, root_path: str) -> Library:
        """Update a library's root path.

        Args:
            library: Domain ``Library`` (natural identity).
            root_path: New filesystem root path.

        Returns:
            The updated domain ``Library`` value.

        """
        update_library_root(
            db=self.db,
            base_library_root=self.cfg.library_root,
            library=library,
            root_path=root_path,
        )
        return self._get_library_or_error(library)

    def update_library(
        self,
        library: Library,
        *,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> Library:
        """Update library properties.

        Args:
            library: Domain ``Library`` (natural identity).
            name: New display name (optional).
            root_path: New filesystem root path (optional).
            is_enabled: New enabled state (optional).
            watch_mode: New watch mode ('off', 'event', or 'poll') (optional).
            file_write_mode: New tag write mode ('none', 'minimal', or 'full') (optional).
            library_auto_write: New auto-write setting (optional).

        Returns:
            The updated domain ``Library`` value.

        """
        # Validate library exists
        self._get_library_or_error(library)

        normalized_root_path = None
        if root_path is not None:
            normalized_root_path = resolve_library_root(self.db, self.cfg.library_root, library, root_path)

        if normalized_root_path is not None:
            update_library_record(
                self.db,
                library,
                name=name,
                root_path=normalized_root_path,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
            )
        elif (
            name is not None
            or is_enabled is not None
            or watch_mode is not None
            or file_write_mode is not None
            or library_auto_write is not None
        ):
            self.update_library_metadata(
                library,
                name=name,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
            )

        return self.get_library(library)

    def delete_library(self, library: Library) -> bool:
        """Stop all library-scoped work and delete the library.

        Coordinated lifecycle: stops the file watcher, cooperatively cancels and
        joins the library's scan and tag-write background tasks, verifies
        quiescence, then removes the library's persistence state. Rejects
        deletion if any library-scoped task refuses to quiesce.

        Args:
            library: Domain ``Library`` (natural identity) to delete.

        Returns:
            True if the library was deleted, False if it was not found.

        Raises:
            RuntimeError: If library-scoped work cannot be quiesced within the
                configured timeout.

        Note:
            The watcher service keys observers by ``str``; the natural
            ``Library.name`` is used as the watcher key. The watcher service
            internals still refer to the key as a "library database ID" and need
            a natural-name pass (P4-S8).

        """
        if self.file_watcher_service is not None and library.name in self.file_watcher_service.observers:
            self.file_watcher_service.stop_watching_library(library.name)

        self._quiesce_library_tasks(library)

        return delete_library(db=self.db, library=library)

    def _quiesce_library_tasks(self, library: Library) -> None:
        """Cancel and join all library-scoped background tasks.

        Signals and joins the library's scan and tag-write tasks, then verifies
        both have fully stopped (including their completion callbacks) before
        returning.

        Raises:
            RuntimeError: If a task is still running after the quiescence timeout.

        """
        if self.background_tasks is None:
            return
        background_tasks = self.background_tasks

        scan_task_id = library_task_id(library, "scan")
        write_task_id = write_tags_task_id(library)

        scan_finished = background_tasks.cancel_and_join(scan_task_id, _QUIESCE_TIMEOUT_SECONDS)
        write_finished = background_tasks.cancel_and_join(write_task_id, _QUIESCE_TIMEOUT_SECONDS)

        if not scan_finished:
            msg = f"Cannot delete library {library.name!r}: scan task is still running"
            raise RuntimeError(msg)
        if not write_finished:
            msg = f"Cannot delete library {library.name!r}: tag-write task is still running"
            raise RuntimeError(msg)

    def update_library_metadata(
        self,
        library: Library,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> Library:
        """Update library metadata fields.

        Only the provided keyword arguments are updated; omitted fields are
        left unchanged. Delegates to the ``UpdateLibraryMetadataComp``
        component for persistence.

        Args:
            library: Domain ``Library`` (natural identity) to update.
            name: Optional new display name for the library.
            is_enabled: Optionally enable or disable the library.
            watch_mode: Optional watch mode (e.g. ``"polling"``, ``"inotify"``).
            file_write_mode: Optional file write mode (``"none"``, ``"minimal"``, ``"full"``).
            library_auto_write: When True, tags are written automatically after
                ML processing completes.

        Returns:
            The updated domain ``Library`` value.

        Raises:
            ValueError: If the library does not exist.

        """
        self._get_library_or_error(library)
        UpdateLibraryMetadataComp(self.db).update(
            library,
            name=name,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )

        return self._get_library_or_error(library)

    def clear_library_data(self) -> None:
        """Clear all library data (files, tags, scan queue).

        Wipes all library files, tags, edges, vectors, scan records, and
        pipeline states from the database. Requires no scans to be running.
        Intended for use when a full re-import is needed.

        Raises:
            RuntimeError: If a library scan is currently running.

        """
        clear_library_data(db=self.db, library_root=self.cfg.library_root)
