"""Library folders operations for ArangoDB.

Tracks folder metadata for quick scan optimization.
Quick scans check folder mtime and file_count to skip unchanged folders.
"""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.time_helper import now_ms


class LibraryFoldersOperations:
    """Operations for the library_folders collection."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("library_folders")

    def upsert_folder(
        self,
        library_id: str,
        folder_path: str,
        mtime: int,
        file_count: int,
    ) -> str:
        """Insert or update a folder record.

        Args:
            library_id: ID of owning library
            folder_path: Relative folder path (POSIX-style, e.g., "Rock/Beatles")
            mtime: Folder modification time (from os.stat)
            file_count: Number of audio files in this folder

        Returns:
            Document _id
        """
        scanned_at = now_ms().value
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                UPSERT { library_id: @library_id, path: @path }
                INSERT {
                    library_id: @library_id,
                    path: @path,
                    mtime: @mtime,
                    file_count: @file_count,
                    last_scanned_at: @scanned_at
                }
                UPDATE {
                    mtime: @mtime,
                    file_count: @file_count,
                    last_scanned_at: @scanned_at
                }
                IN library_folders
                RETURN NEW._id
                """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "library_id": library_id,
                        "path": folder_path,
                        "mtime": mtime,
                        "file_count": file_count,
                        "scanned_at": scanned_at,
                    },
                ),
            ),
        )
        results = list(cursor)
        return results[0] if results else ""

    def get_folder(
        self,
        library_id: str,
        folder_path: str,
    ) -> dict[str, Any] | None:
        """Get a folder record.

        Args:
            library_id: ID of owning library
            folder_path: Relative folder path

        Returns:
            Folder dict or None if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR folder IN library_folders
                    FILTER folder.library_id == @library_id
                    FILTER folder.path == @path
                    RETURN folder
                """,
                bind_vars={
                    "library_id": library_id,
                    "path": folder_path,
                },
            ),
        )
        results = list(cursor)
        return results[0] if results else None

    def get_all_folders_for_library(
        self,
        library_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Get all folder records for a library as a dict keyed by path.

        Args:
            library_id: ID of library

        Returns:
            Dict mapping path to folder record
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR folder IN library_folders
                    FILTER folder.library_id == @library_id
                    RETURN folder
                """,
                bind_vars={"library_id": library_id},
            ),
        )
        return {folder["path"]: folder for folder in cursor}

    def delete_folders_for_library(self, library_id: str) -> int:
        """Delete all folder records for a library.

        Args:
            library_id: ID of library

        Returns:
            Number of folders deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR folder IN library_folders
                    FILTER folder.library_id == @library_id
                    REMOVE folder IN library_folders
                    COLLECT WITH COUNT INTO deleted
                    RETURN deleted
                """,
                bind_vars={"library_id": library_id},
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def delete_missing_folders(
        self,
        library_id: str,
        existing_paths: set[str],
    ) -> int:
        """Delete folder records that no longer exist on disk.

        Args:
            library_id: ID of library
            existing_paths: Set of folder paths that exist on disk

        Returns:
            Number of folders deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR folder IN library_folders
                    FILTER folder.library_id == @library_id
                    FILTER folder.path NOT IN @existing_paths
                    REMOVE folder IN library_folders
                    COLLECT WITH COUNT INTO deleted
                    RETURN deleted
                """,
                bind_vars={
                    "library_id": library_id,
                    "existing_paths": list(existing_paths),
                },
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def get_folder_count_for_library(self, library_id: str) -> int:
        """Get total folder count for a library.

        Args:
            library_id: ID of library

        Returns:
            Number of folders tracked
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                RETURN LENGTH(
                    FOR folder IN library_folders
                        FILTER folder.library_id == @library_id
                        RETURN 1
                )
                """,
                bind_vars={"library_id": library_id},
            ),
        )
        results = list(cursor)
        return results[0] if results else 0
