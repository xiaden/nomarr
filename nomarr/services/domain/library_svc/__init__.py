"""Library service package.

This package provides a modular LibraryService composed from focused mixins:
- LibraryAdminMixin: Library CRUD, configuration, and data management
- LibraryScanMixin: Scanning operations, status, and history
- LibraryQueryMixin: Statistics, search, and tag discovery
- LibraryFilesMixin: File tag operations and path handling
- LibraryEntitiesMixin: Entity navigation (placeholder)
"""

from __future__ import annotations

from nomarr.components.infrastructure.health_comp import HealthComp
from nomarr.components.library.get_library_comp import GetLibraryComp
from nomarr.components.library.get_library_counts_comp import GetLibraryCountsComp
from nomarr.components.library.list_libraries_comp import ListLibrariesComp
from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp

from .admin import LibraryAdminMixin
from .config import LibraryServiceConfig
from .entities import LibraryEntitiesMixin
from .files import LibraryFilesMixin
from .query import LibraryQueryMixin
from .scan import LibraryScanMixin


class LibraryService(LibraryAdminMixin, LibraryScanMixin, LibraryQueryMixin, LibraryFilesMixin, LibraryEntitiesMixin):
    """
    Unified library management service.

    This service composes functionality from multiple focused mixins:
    - Admin: Library CRUD, configuration checks, clear data
    - Scan: Scanning operations, status, history
    - Query: Statistics, search, tag discovery
    - Files: File tag operations, reconciliation, path resolution
    - Entities: Entity navigation (placeholder)

    Usage:
        db = Database(...)
        cfg = LibraryServiceConfig(namespace="nom", tagger_version="abc123def456", library_root="/music")
        service = LibraryService(db=db, cfg=cfg)

        # Admin operations
        libraries = service.list_libraries()
        service.create_library(name="Main", path="/music")

        # Scan operations
        service.start_scan(library_id="lib-123")
        status = service.get_status(library_id="lib-123")

        # Query operations
        stats = service.get_library_stats()
        files = service.search_files(query="rock")

        # File operations
        tags = service.get_file_tags(file_id="file-123")
        service.cleanup_orphaned_tags()
    """

    def __init__(
        self,
        cfg: LibraryServiceConfig,
        get_library: GetLibraryComp,
        list_libraries: ListLibrariesComp,
        get_library_counts: GetLibraryCountsComp,
        update_library_metadata: UpdateLibraryMetadataComp,
        health: HealthComp,
        background_tasks: object | None = None,
    ) -> None:
        """
        Initialize LibraryService.

        Args:
            cfg: Service configuration (namespace, library_root)
            get_library: Component for fetching library records
            list_libraries: Component for listing libraries
            get_library_counts: Component for file/folder counts
            update_library_metadata: Component for updating library metadata
            health: Component for health monitoring
            background_tasks: BackgroundTaskService for async scan operations
        """
        self.cfg = cfg
        self.get_library = get_library
        self.list_libraries = list_libraries
        self.get_library_counts = get_library_counts
        self.update_library_metadata = update_library_metadata
        self.health = health
        self.background_tasks = background_tasks


__all__ = ["LibraryService", "LibraryServiceConfig"]
