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
        return str(rows[0]) if rows else ""

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
        query = """
        FOR lib IN libraries
          FILTER !@enabled_only OR lib.is_enabled == true
          RETURN lib
        """
        rows = execute(self._db, query, {"enabled_only": enabled_only})
        return [row for row in rows if isinstance(row, dict)]

    def list_library_keys(self) -> list[str]:
        query = """
        FOR lib IN libraries
          RETURN lib._key
        """
        rows = execute(self._db, query, {})
        return [row for row in rows if isinstance(row, str)]

    def update_library_by_id(self, library_id: str, fields: dict[str, Any]) -> None:
        query = """
        UPDATE PARSE_IDENTIFIER(@library_id).key WITH @fields IN libraries
        """
        execute(self._db, query, {"library_id": library_id, "fields": fields})
