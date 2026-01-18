"""Library service package.

This package provides a modular LibraryService composed from focused mixins:
- LibraryAdminMixin: Library CRUD, configuration, and data management
- LibraryScanMixin: Scanning operations, status, and history
- LibraryQueryMixin: Statistics, search, and tag discovery
- LibraryFilesMixin: File tag operations and path handling
- LibraryEntitiesMixin: Entity navigation (placeholder)
"""

from __future__ import annotations

from nomarr.persistence.db import Database

from .admin import LibraryAdminMixin
from .config import LibraryServiceConfig
from .entities import LibraryEntitiesMixin
from .files import LibraryFilesMixin
from .query import LibraryQueryMixin
from .scan import LibraryScanMixin


class LibraryService(
    LibraryAdminMixin,
    LibraryScanMixin,
    LibraryQueryMixin,
    LibraryFilesMixin,
    LibraryEntitiesMixin,
):
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
        cfg = LibraryServiceConfig(namespace="NOMARR", library_root="/music")
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
        db: Database,
        cfg: LibraryServiceConfig,
        background_tasks: object | None = None,
    ) -> None:
        """
        Initialize LibraryService.

        Args:
            db: Database instance for persistence operations
            cfg: Service configuration (namespace, library_root)
            background_tasks: BackgroundTaskService for async scan operations
        """
        self.db = db
        self.cfg = cfg
        self.background_tasks = background_tasks


__all__ = ["LibraryService", "LibraryServiceConfig"]
