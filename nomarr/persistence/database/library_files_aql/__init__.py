"""Library files operations for ArangoDB.

This is a multi-file subpackage that splits LibraryFilesOperations into logical modules:
- crud.py: Basic CRUD operations
- queries.py: General file queries
- calibration.py: Calibration-specific queries
- chromaprint.py: Chromaprint queries
- reconciliation.py: File reconciliation operations
- stats.py: Statistics queries
- status.py: Status queries
- tracks.py: Track-specific queries

The main class LibraryFilesOperations composes these mixins.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

from typing import TYPE_CHECKING

from nomarr.persistence.arango_client import DatabaseLike

from .calibration import LibraryFilesCalibrationMixin
from .chromaprint import LibraryFilesChromaprintMixin
from .crud import LibraryFilesCrudMixin
from .queries import LibraryFilesQueriesMixin
from .reconciliation import LibraryFilesReconciliationMixin
from .stats import LibraryFilesStatsMixin
from .status import LibraryFilesStatusMixin
from .tracks import LibraryFilesTracksMixin

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryFilesOperations(
    LibraryFilesCrudMixin,
    LibraryFilesQueriesMixin,
    LibraryFilesStatusMixin,
    LibraryFilesCalibrationMixin,
    LibraryFilesReconciliationMixin,
    LibraryFilesStatsMixin,
    LibraryFilesChromaprintMixin,
    LibraryFilesTracksMixin,
):
    """Operations for the library_files collection."""

    def __init__(self, db: DatabaseLike, parent_db: "Database | None" = None) -> None:
        self.db = db
        self.collection = db.collection("library_files")
        self.parent_db = parent_db


__all__ = ["LibraryFilesOperations"]
