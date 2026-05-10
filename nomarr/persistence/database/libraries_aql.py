"""Explicit library document operations backed by AQL."""

from __future__ import annotations

from typing import Any

from nomarr.persistence.aql.primitives import (
    get_filtered_docs,
    get_many_by_field,
    insert_document,
    list_field_values,
    update_document_by_key,
)
from nomarr.persistence.arango_client import SafeDatabase


class LibrariesAqlOperations:
    """Operations for library CRUD and query paths via reusable AQL templates."""

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def insert_library(self, payload: dict[str, Any]) -> str:
        return insert_document(self._db, "libraries", payload)

    def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
        rows = get_many_by_field(
            self._db,
            "libraries",
            "_id",
            library_id,
            limit=1,
            allowed_fields={"_id"},
        )
        return rows[0] if rows else None

    def get_library_by_key(self, library_key: str) -> dict[str, Any] | None:
        rows = get_many_by_field(
            self._db,
            "libraries",
            "_key",
            library_key,
            limit=1,
            allowed_fields={"_key"},
        )
        return rows[0] if rows else None

    def get_library_by_name(self, name: str) -> dict[str, Any] | None:
        rows = get_many_by_field(
            self._db,
            "libraries",
            "name",
            name,
            limit=1,
            allowed_fields={"name"},
        )
        return rows[0] if rows else None

    def list_libraries(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        rows = get_filtered_docs(
            self._db,
            "libraries",
            filters={"is_enabled": True} if enabled_only else None,
            allowed_fields={"is_enabled"},
        )
        return [row for row in rows if isinstance(row, dict)]

    def list_library_keys(self) -> list[str]:
        rows = list_field_values(
            self._db,
            "libraries",
            "_key",
            allowed_fields={"_key"},
        )
        return [row for row in rows if isinstance(row, str)]

    def update_library_by_id(self, library_id: str, fields: dict[str, Any]) -> None:
        if not library_id.startswith("libraries/"):
            raise ValueError("library_id must be a full Arango _id like 'libraries/<key>'")
        library_key = library_id.split("/", maxsplit=1)[1]
        update_document_by_key(self._db, "libraries", library_key, fields)
