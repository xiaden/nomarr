"""Library folders operations for ArangoDB.

Tracks folder metadata for quick scan optimization.
Quick scans check folder mtime and file_count to skip unchanged folders.
"""

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class LibraryFoldersOperations:
    """Operations for the library_folders collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("library_folders")

    def _make_folder_key(self, library_id: str, folder_path: str) -> str:
        """Generate a stable document key from library + path.

        Uses MD5 hash for uniqueness across libraries while keeping
        the key deterministic.
        """
        composite = f"{library_id}/{folder_path}"
        return hashlib.md5(composite.encode("utf-8")).hexdigest()

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
        folder_key = self._make_folder_key(library_id, folder_path)
        folder_id = f"library_folders/{folder_key}"

        # Upsert folder document using key-based lookup (no library_id in body)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                UPSERT { _key: @folder_key }
                INSERT {
                    _key: @folder_key,
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
                    "dict[str, Any]",
                    {
                        "folder_key": folder_key,
                        "path": folder_path,
                        "mtime": mtime,
                        "file_count": file_count,
                        "scanned_at": scanned_at,
                    },
                ),
            ),
        )
        list(cursor)  # Execute upsert

        # Upsert ownership edge (library -> folder)
        self.db.aql.execute(
            """
            UPSERT { _from: @library_id, _to: @folder_id }
            INSERT { _from: @library_id, _to: @folder_id }
            UPDATE {}
            IN library_contains_folder
            """,
            bind_vars={
                "library_id": library_id,
                "folder_id": folder_id,
            },
        )

        return folder_id

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
        folder_key = self._make_folder_key(library_id, folder_path)
        folder_id = f"library_folders/{folder_key}"

        # Direct document lookup using computed key (key encodes library ownership)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET folder = DOCUMENT(@folder_id)
                FILTER folder != null
                RETURN folder
                """,
                bind_vars={"folder_id": folder_id},
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
            "Cursor",
            self.db.aql.execute(
                """
                FOR folder IN OUTBOUND @library_id library_contains_folder
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
            "Cursor",
            self.db.aql.execute(
                """
                LET folders_to_delete = (
                    FOR folder, edge IN OUTBOUND @library_id library_contains_folder
                        REMOVE edge IN library_contains_folder
                        REMOVE folder IN library_folders
                        RETURN 1
                )
                RETURN LENGTH(folders_to_delete)
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
            "Cursor",
            self.db.aql.execute(
                """
                LET folders_to_delete = (
                    FOR folder, edge IN OUTBOUND @library_id library_contains_folder
                        FILTER folder.path NOT IN @existing_paths
                        REMOVE edge IN library_contains_folder
                        REMOVE folder IN library_folders
                        RETURN 1
                )
                RETURN LENGTH(folders_to_delete)
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
            "Cursor",
            self.db.aql.execute(
                """
                RETURN LENGTH(
                    FOR folder IN OUTBOUND @library_id library_contains_folder
                        RETURN 1
                )
                """,
                bind_vars={"library_id": library_id},
            ),
        )
        results = list(cursor)
        return results[0] if results else 0
