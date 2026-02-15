"""Status operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesStatusMixin:
    """Status operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def mark_file_tagged(self, file_id: str, tagged_version: str) -> None:
        """Mark file as tagged.

        Accepts _id directly (no lookup needed).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            tagged_version: Tagged version string

        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                tagged: true,
                tagged_version: @version,
                last_tagged_at: @timestamp,
                needs_tagging: false
            } IN library_files
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "version": tagged_version, "timestamp": now_ms().value},
            ),
        )

    def mark_file_invalid(self, path: str) -> None:
        """Mark file as no longer existing on disk.

        Args:
            path: File path to mark invalid

        """
        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path == @path
                UPDATE file WITH { is_valid: false } IN library_files
            """,
            bind_vars={"path": path},
        )

    def bulk_mark_invalid(self, paths: list[str]) -> None:
        """Mark multiple files as invalid.

        DEPRECATED: Use bulk_delete_files instead. Soft deletes create state explosion.

        Args:
            paths: List of file paths to mark invalid

        """
        if not paths:
            return

        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path IN @paths
                UPDATE file WITH { is_valid: false } IN library_files
            """,
            bind_vars={"paths": paths},
        )

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if library has any files with ML tags.

        Args:
            library_id: Library ID

        Returns:
            True if library has at least one tagged file

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.library_id == @library_id AND file.tagged == true
                SORT file._key
                LIMIT 1
                RETURN 1
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        result = list(cursor)
        return len(result) > 0

    def get_files_needing_tagging(self, library_id: int | None, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Get files that need ML tagging.

        Args:
            library_id: Library ID (or None for all libraries)
            paths: Optional specific file paths to filter

        Returns:
            List of file dicts needing tagging

        """
        filters = ["file.needs_tagging == true", "file.is_valid == true"]
        bind_vars: dict[str, Any] = {}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        if paths:
            filters.append("file.path IN @paths")
            bind_vars["paths"] = paths

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

    def discover_next_unprocessed_file(self) -> dict[str, Any] | None:
        """Discover next file needing ML tagging for worker discovery.

        Query optimized for discovery-based workers:
        - Filters: needs_tagging=true, is_valid=true
        - Deterministic ordering by _key for consistent work distribution
        - LIMIT 1 for single-file claiming

        Returns:
            File dict or None if no work available

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """\
                FOR file IN library_files
                    FILTER file.needs_tagging == true
                    FILTER file.is_valid == true
                    SORT file._key
                    LIMIT 1
                    RETURN file
                """,
            ),
        )
        return next(iter(cursor), None)
