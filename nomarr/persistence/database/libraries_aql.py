from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


class LibrariesAqlOperations:
    """Thin Tier 2 bindings for the ``libraries`` collection."""

    COLLECTION = "libraries"
    ALLOWED_FIELDS = frozenset(
        {
            "name",
            "root_path",
            "is_enabled",
            "watch_mode",
            "file_write_mode",
            "library_auto_write",
            "created_at",
            "updated_at",
            "vector_group_size",
            "vector_search_thoroughness",
        },
    )

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def add_library(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.COLLECTION, payload)

    def get_library(self, library_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [_extract_key(library_id)])
        return results[0] if results else None

    def get_library_by_name(self, name: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.COLLECTION,
            "name",
            name,
            limit=1,
            allowed_fields=self.ALLOWED_FIELDS,
        )
        return results[0] if results else None

    def list_libraries(self, *, enabled_only: bool = False) -> list[Document]:
        filters = {"is_enabled": True} if enabled_only else {}
        return primitives.get_filtered_docs(
            self._db,
            self.COLLECTION,
            filters=filters,
            sort_field="name",
            limit=None,
            allowed_fields=self.ALLOWED_FIELDS,
        )

    def list_library_keys(self) -> list[str]:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                SORT doc._key
                RETURN doc._key
            """,
            bind_vars={"@collection": self.COLLECTION},
        )
        return list(cursor)

    def update_library(self, library_id: str, fields: dict[str, Any]) -> None:
        primitives.update_document_by_key(self._db, self.COLLECTION, _extract_key(library_id), fields)

    def delete_library(self, library_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.COLLECTION, [_extract_key(library_id)])
