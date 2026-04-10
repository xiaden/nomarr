"""Inventory and folder listing queries for library_files."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesInventoryMixin:
    """Inventory and folder-oriented query operations for ``library_files``."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def get_file_modified_times(self) -> dict[str, int]:
        """Get all file paths and their modified times.

        Returns:
            Dict mapping file path to modified_time (milliseconds)

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN { path: file.path, modified_time: file.modified_time }
            """,
            ),
        )
        return {item["path"]: item["modified_time"] for item in cursor}

    def get_all_library_paths(self) -> list[str]:
        """Get all library file paths.

        Returns:
            List of file paths

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                RETURN file.path
            """,
            ),
        )
        return list(cursor)

    def list_all_file_ids(self, limit: int | None = None) -> list[str]:
        """Return all library file IDs ordered by key, optionally limited."""
        if limit is None:
            query = """
                FOR file IN library_files
                    SORT file._key
                    RETURN file._id
            """
            bind_vars: dict[str, Any] = {}
        else:
            query = """
                FOR file IN library_files
                    SORT file._key
                    LIMIT @limit
                    RETURN file._id
            """
            bind_vars = {"limit": limit}

        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),
        )
        return list(cursor)

    def get_folder_rel_paths(self, library_id: str) -> set[str]:
        """Get all known folder rel_paths for a library.

        Queries the ``library_folders`` cache collection via edge traversal,
        since folder ownership is tracked via ``library_contains_folder`` edges.

        Args:
            library_id: Library document ``_id``

        Returns:
            Set of POSIX folder rel_paths (e.g. ``{"Rock/Beatles", ""}``). Empty string
            represents the library root folder.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR folder IN OUTBOUND @library_id library_contains_folder
                RETURN folder.path
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        return set(cursor)

    def get_files_for_folder(
        self,
        library_id: str,
        folder_rel_path: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all file documents for a single folder.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Args:
            library_id: Library document ``_id``
            folder_rel_path: POSIX relative folder path (``""`` for library root)

        Returns:
            Dict mapping absolute file path → file document.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN OUTBOUND @library_id library_contains_file
                FILTER (
                    (@folder_rel_path == "" AND NOT CONTAINS(file.normalized_path, "/"))
                    OR
                    (@folder_rel_path != "" AND STARTS_WITH(file.normalized_path, CONCAT(@folder_rel_path, "/")))
                )
                RETURN file
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"library_id": library_id, "folder_rel_path": folder_rel_path},
                ),
            ),
        )
        return {f["path"]: f for f in cursor}

    def get_files_for_folders(
        self,
        library_id: str,
        folder_rel_paths: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Batch-fetch file documents for multiple folders.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Intended for loading file docs for vanished folders before the
        scan loop starts so they can seed the ``missing_docs`` list.

        Args:
            library_id: Library document ``_id``
            folder_rel_paths: POSIX relative paths of the folders.

        Returns:
            Dict mapping absolute file path → file document.

        """
        if not folder_rel_paths:
            return {}
        has_root = "" in folder_rel_paths
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            LET has_root = @has_root
            FOR file IN OUTBOUND @library_id library_contains_file
                FILTER (
                    (has_root AND NOT CONTAINS(file.normalized_path, "/"))
                    OR
                    LENGTH(
                        FOR fp IN @folder_rel_paths
                            FILTER fp != "" AND STARTS_WITH(file.normalized_path, CONCAT(fp, "/"))
                            LIMIT 1
                            RETURN 1
                    ) > 0
                )
                RETURN file
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "folder_rel_paths": folder_rel_paths,
                        "has_root": has_root,
                    },
                ),
            ),
        )
        return {f["path"]: f for f in cursor}

    def count_library_files(self, library_id: str) -> int:
        """Count total files for a library.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Used to set accurate progress totals at scan start without
        loading all file documents.

        Args:
            library_id: Library document ``_id``

        Returns:
            Total number of file documents for the library.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN OUTBOUND @library_id library_contains_file
                COLLECT WITH COUNT INTO total
                RETURN total
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        return next(iter(cursor), 0)
