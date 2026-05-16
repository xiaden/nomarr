from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


class ScanAqlOperations:
    """Thin Tier 2 bindings for ``library_scans``."""

    COLLECTION = "library_scans"
    ALLOWED_FIELDS = frozenset(
        {
            "library_key",
            "status",
            "files_processed",
            "files_total",
            "completed_at",
            "started_at",
            "error",
            "scan_type",
        },
    )

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_scan_record(self, library_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.COLLECTION,
            "library_key",
            _extract_key(library_id),
            limit=1,
            allowed_fields=self.ALLOWED_FIELDS,
        )
        return results[0] if results else None

    def add_scan_record(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.COLLECTION, payload)

    def update_scan_record(self, scan_id: str, fields: dict[str, Any]) -> None:
        primitives.update_document_by_key(self._db, self.COLLECTION, _extract_key(scan_id), fields)

    def _delete_scan_record(self, scan_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.COLLECTION, [_extract_key(scan_id)])
