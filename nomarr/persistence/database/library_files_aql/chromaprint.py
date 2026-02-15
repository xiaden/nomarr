"""Chromaprint operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesChromaprintMixin:
    """Chromaprint operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def get_files_by_chromaprint(self, chromaprint: str, library_id: int | None = None) -> list[dict[str, Any]]:
        """Get library files matching a chromaprint (for move detection).

        Args:
            chromaprint: Audio fingerprint hash to search for
            library_id: Optional library ID to restrict search

        Returns:
            List of file dicts with matching chromaprint

        """
        filters = ["file.chromaprint == @chromaprint"]
        bind_vars: dict[str, Any] = {"chromaprint": chromaprint}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        filter_clause = " AND ".join(filters)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                FILTER {filter_clause}
                RETURN file
            """,
                bind_vars=bind_vars,
            ),
        )
        return list(cursor)

    def set_chromaprint(self, file_id: str, chromaprint: str) -> None:
        """Set chromaprint for a file.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            chromaprint: Audio fingerprint hash

        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                chromaprint: @chromaprint
            } IN library_files
            """,
            bind_vars={"file_id": file_id, "chromaprint": chromaprint},
        )
