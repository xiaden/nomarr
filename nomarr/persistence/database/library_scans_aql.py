"""Library scans operations for ArangoDB.

Manages the library_scans collection which tracks scan state per library.
Each library has exactly one scan document with status, progress, etc.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)


class LibraryScansOperations:
    """Operations for library_scans collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("library_scans")

    def get_or_create_scan(self, library_id: str) -> dict[str, Any]:
        """Get scan state for library, creating default if needed.

        Args:
            library_id: Full document ID of library (libraries/{key})

        Returns:
            Scan state dict with status, files_processed, files_total, etc.

        """
        # Extract key from library_id
        library_key = library_id.split("/")[-1]

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET existing = DOCUMENT(CONCAT("library_scans/", @library_key))
                LET scan = existing != null ? existing : (
                    INSERT {
                        _key: @library_key,
                        status: "idle",
                        files_processed: 0,
                        files_total: 0,
                        completed_at: null,
                        started_at: null,
                        error: null,
                        scan_type: null
                    } INTO library_scans
                    RETURN NEW
                )[0]

                // Ensure edge exists
                UPSERT { _from: @library_id, _to: CONCAT("library_scans/", @library_key) }
                INSERT { _from: @library_id, _to: CONCAT("library_scans/", @library_key) }
                UPDATE {}
                IN library_has_scan

                RETURN scan
                """,
                bind_vars={"library_id": library_id, "library_key": library_key},
            ),
        )
        result = next(cursor, None)
        return result if result else self._default_scan_state(library_key)

    def update_scan(self, library_id: str, **fields: Any) -> dict[str, Any]:
        """Update scan state fields.

        Args:
            library_id: Full document ID of library
            **fields: Fields to update (status, files_processed, etc.)

        Returns:
            Updated scan state

        """
        library_key = library_id.split("/")[-1]

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                UPSERT { _key: @library_key }
                INSERT MERGE({
                    _key: @library_key,
                    status: "idle",
                    files_processed: 0,
                    files_total: 0,
                    completed_at: null,
                    started_at: null,
                    error: null,
                    scan_type: null
                }, @fields)
                UPDATE @fields
                IN library_scans
                RETURN NEW
                """,
                bind_vars={"library_key": library_key, "fields": fields},
            ),
        )
        result = next(cursor, None)
        return result if result else {}

    def get_scan_state(self, library_id: str) -> dict[str, Any] | None:
        """Get scan state for library.

        Args:
            library_id: Full document ID of library

        Returns:
            Scan state dict or None if no scan exists

        """
        library_key = library_id.split("/")[-1]
        scan = self.collection.get(library_key)
        return dict(scan) if scan else None  # type: ignore[arg-type]

    def _default_scan_state(self, library_key: str) -> dict[str, Any]:
        """Return default scan state."""
        return {
            "_key": library_key,
            "status": "idle",
            "files_processed": 0,
            "files_total": 0,
            "completed_at": None,
            "started_at": None,
            "error": None,
            "scan_type": None,
        }
