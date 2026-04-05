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

    def get_files_by_chromaprint(self, chromaprint: str, library_id: str | None = None) -> list[dict[str, Any]]:
        """Get library files matching a chromaprint (for move detection).

        Uses ``library_contains_file`` edge traversal when scoped to a library.
        Uses ``collection.find()`` for global search (no AQL needed).

        Args:
            chromaprint: Audio fingerprint hash to search for
            library_id: Optional library document ``_id`` to restrict search

        Returns:
            List of file dicts with matching chromaprint

        """
        if library_id is not None:
            # Edge traversal requires AQL — no python-arango API equivalent
            cursor = cast(
                "Cursor",
                self.db.aql.execute(
                    """
                    FOR file IN OUTBOUND @library_id library_contains_file
                        FILTER file.chromaprint == @chromaprint
                        RETURN file
                    """,
                    bind_vars={"library_id": library_id, "chromaprint": chromaprint},
                ),
            )
            return list(cursor)

        # Simple equality filter — use python-arango API, no AQL
        return list(self.collection.find({"chromaprint": chromaprint}))

    def set_chromaprint(self, file_id: str, chromaprint: str) -> None:
        """Set chromaprint for a file.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            chromaprint: Audio fingerprint hash

        """
        doc_key = file_id.split("/", 1)[1] if "/" in file_id else file_id
        self.collection.update({"_key": doc_key, "chromaprint": chromaprint})
