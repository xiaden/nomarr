"""Explicit library document operations backed by AQL."""

from __future__ import annotations

from typing import Any

from nomarr.persistence.aql.primitives import execute
from nomarr.persistence.arango_client import SafeDatabase


class LibrariesAqlOperations:
    """Reviewed, explicit operations for the `libraries` collection."""

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def insert_library(self, payload: dict[str, Any]) -> str:
        query = """
        INSERT @payload IN libraries
        RETURN NEW._id
        """
        rows = execute(self._db, query, {"payload": payload})
        if not rows or not isinstance(rows[0], str):
            raise RuntimeError("Failed to insert library document")
        return rows[0]

    def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
        query = """
        FOR lib IN libraries
          FILTER lib._id == @library_id
          LIMIT 1
          RETURN lib
        """
        rows = execute(self._db, query, {"library_id": library_id})
        first = rows[0] if rows else None
        return first if isinstance(first, dict) else None

    def get_library_by_key(self, library_key: str) -> dict[str, Any] | None:
        query = """
        FOR lib IN libraries
          FILTER lib._key == @library_key
          LIMIT 1
          RETURN lib
        """
        rows = execute(self._db, query, {"library_key": library_key})
        first = rows[0] if rows else None
        return first if isinstance(first, dict) else None

    def get_library_by_name(self, name: str) -> dict[str, Any] | None:
        query = """
        FOR lib IN libraries
          FILTER lib.name == @name
          LIMIT 1
          RETURN lib
        """
        rows = execute(self._db, query, {"name": name})
        first = rows[0] if rows else None
        return first if isinstance(first, dict) else None

    def list_libraries(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        if enabled_only:
            query = """
            FOR lib IN libraries
              FILTER lib.is_enabled == true
              RETURN lib
            """
        else:
            query = """
            FOR lib IN libraries
              RETURN lib
            """
        rows = execute(self._db, query, {})
        return [row for row in rows if isinstance(row, dict)]

    def list_library_keys(self) -> list[str]:
        query = """
        FOR lib IN libraries
          RETURN lib._key
        """
        rows = execute(self._db, query, {})
        return [row for row in rows if isinstance(row, str)]

    def update_library_by_id(self, library_id: str, fields: dict[str, Any]) -> None:
        if not library_id.startswith("libraries/"):
            raise ValueError("library_id must be a full Arango _id like 'libraries/<key>'")
        library_key = library_id.split("/", maxsplit=1)[1]
        query = """
        UPDATE @library_key WITH @fields IN libraries
        """
        execute(self._db, query, {"library_key": library_key, "fields": fields})
