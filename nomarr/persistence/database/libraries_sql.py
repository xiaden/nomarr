"""Libraries operations for the libraries table."""

import sqlite3
from typing import Any

from nomarr.helpers.time_helper import now_ms


class LibrariesOperations:
    """Operations for the libraries table (library management within library_root)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_library(
        self,
        name: str,
        root_path: str,
        is_enabled: bool = True,
        is_default: bool = False,
    ) -> int:
        """
        Create a new library entry.

        Args:
            name: Library name (must be unique)
            root_path: Absolute path to library root
            is_enabled: Whether library is enabled for scanning
            is_default: Whether this is the default library

        Returns:
            Library ID

        Raises:
            sqlite3.IntegrityError: If name already exists
        """
        now = now_ms()

        # If setting as default, clear other defaults first
        if is_default:
            self.conn.execute("UPDATE libraries SET is_default = 0")

        cursor = self.conn.execute(
            """
            INSERT INTO libraries (name, root_path, is_enabled, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, root_path, int(is_enabled), int(is_default), now, now),
        )
        self.conn.commit()
        library_id = cursor.lastrowid
        if library_id is None:
            raise RuntimeError("Failed to create library: no ID returned")
        return library_id

    def get_library(self, library_id: int) -> dict[str, Any] | None:
        """
        Get a library by ID.

        Args:
            library_id: Library ID

        Returns:
            Library dict or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT id, name, root_path, is_enabled, is_default,
                   scan_status, scan_progress, scan_total, scanned_at, scan_error,
                   created_at, updated_at
            FROM libraries
            WHERE id = ?
            """,
            (library_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "root_path": row[2],
            "is_enabled": bool(row[3]),
            "is_default": bool(row[4]),
            "scan_status": row[5],
            "scan_progress": row[6],
            "scan_total": row[7],
            "scanned_at": row[8],
            "scan_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    def get_library_by_name(self, name: str) -> dict[str, Any] | None:
        """
        Get a library by name.

        Args:
            name: Library name

        Returns:
            Library dict or None if not found
        """
        cursor = self.conn.execute(
            """
            SELECT id, name, root_path, is_enabled, is_default,
                   scan_status, scan_progress, scan_total, scanned_at, scan_error,
                   created_at, updated_at
            FROM libraries
            WHERE name = ?
            """,
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "root_path": row[2],
            "is_enabled": bool(row[3]),
            "is_default": bool(row[4]),
            "scan_status": row[5],
            "scan_progress": row[6],
            "scan_total": row[7],
            "scanned_at": row[8],
            "scan_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    def list_libraries(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """
        List all libraries.

        Args:
            enabled_only: If True, only return enabled libraries

        Returns:
            List of library dicts
        """
        query = """
            SELECT id, name, root_path, is_enabled, is_default,
                   scan_status, scan_progress, scan_total, scanned_at, scan_error,
                   created_at, updated_at
            FROM libraries
        """
        params: tuple = ()

        if enabled_only:
            query += " WHERE is_enabled = 1"

        query += " ORDER BY is_default DESC, name ASC"

        cursor = self.conn.execute(query, params)
        libraries = []
        for row in cursor.fetchall():
            libraries.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "root_path": row[2],
                    "is_enabled": bool(row[3]),
                    "is_default": bool(row[4]),
                    "scan_status": row[5],
                    "scan_progress": row[6],
                    "scan_total": row[7],
                    "scanned_at": row[8],
                    "scan_error": row[9],
                    "created_at": row[10],
                    "updated_at": row[11],
                }
            )
        return libraries

    def get_default_library(self) -> dict[str, Any] | None:
        """
        Get the default library.

        Returns:
            Default library dict or None if no default set
        """
        cursor = self.conn.execute(
            """
            SELECT id, name, root_path, is_enabled, is_default,
                   scan_status, scan_progress, scan_total, scanned_at, scan_error,
                   created_at, updated_at
            FROM libraries
            WHERE is_default = 1
            LIMIT 1
            """,
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "root_path": row[2],
            "is_enabled": bool(row[3]),
            "is_default": bool(row[4]),
            "scan_status": row[5],
            "scan_progress": row[6],
            "scan_total": row[7],
            "scanned_at": row[8],
            "scan_error": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    def update_library(
        self,
        library_id: int,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        is_default: bool | None = None,
    ) -> bool:
        """
        Update a library's properties.

        Args:
            library_id: Library ID
            name: New name (optional)
            root_path: New root path (optional)
            is_enabled: New enabled state (optional)
            is_default: New default state (optional)

        Returns:
            True if updated, False if library not found

        Raises:
            sqlite3.IntegrityError: If name conflicts with existing library
        """
        # Check if library exists
        if not self.get_library(library_id):
            return False

        # If setting as default, clear other defaults first
        if is_default is True:
            self.conn.execute("UPDATE libraries SET is_default = 0")

        # Build update query dynamically based on provided fields
        updates = []
        params: list[int | str] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if root_path is not None:
            updates.append("root_path = ?")
            params.append(root_path)
        if is_enabled is not None:
            updates.append("is_enabled = ?")
            params.append(int(is_enabled))
        if is_default is not None:
            updates.append("is_default = ?")
            params.append(int(is_default))

        if not updates:
            return True  # No changes requested

        # Always update updated_at
        updates.append("updated_at = ?")
        params.append(now_ms())

        # Add library_id to params
        params.append(library_id)

        query = f"UPDATE libraries SET {', '.join(updates)} WHERE id = ?"
        self.conn.execute(query, params)
        self.conn.commit()
        return True

    def delete_library(self, library_id: int) -> bool:
        """
        Delete a library.

        Args:
            library_id: Library ID

        Returns:
            True if deleted, False if not found
        """
        cursor = self.conn.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_default_library(self, library_id: int) -> bool:
        """
        Set a library as the default library (clears other defaults).

        Args:
            library_id: Library ID

        Returns:
            True if set, False if library not found
        """
        # Check if library exists
        if not self.get_library(library_id):
            return False

        # Clear all defaults
        self.conn.execute("UPDATE libraries SET is_default = 0, updated_at = ?", (now_ms(),))

        # Set this one as default
        self.conn.execute(
            "UPDATE libraries SET is_default = 1, updated_at = ? WHERE id = ?",
            (now_ms(), library_id),
        )
        self.conn.commit()
        return True

    def count_libraries(self) -> int:
        """
        Count total number of libraries.

        Returns:
            Total count
        """
        cursor = self.conn.execute("SELECT COUNT(*) FROM libraries")
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def find_library_containing_path(self, file_path: str) -> dict[str, Any] | None:
        """
        Find the library that contains the given file path.

        Uses path prefix matching to determine which library owns a file.
        Returns the most specific (longest) matching library root.

        Args:
            file_path: Absolute file path to check

        Returns:
            Library dict if found, None otherwise

        Example:
            >>> ops.find_library_containing_path("/music/rock/song.mp3")
            {"id": 1, "name": "My Music", "root_path": "/music", ...}
        """
        from pathlib import Path

        # Normalize the input path
        try:
            normalized_path = Path(file_path).resolve()
        except (ValueError, OSError):
            return None

        # Get all libraries ordered by root_path length (longest first)
        # This ensures we match the most specific library
        cursor = self.conn.execute(
            """
            SELECT id, name, root_path, is_enabled, is_default,
                   scan_status, scan_progress, scan_total, scanned_at, scan_error,
                   created_at, updated_at,
                   LENGTH(root_path) as path_len
            FROM libraries
            ORDER BY path_len DESC
            """
        )

        for row in cursor.fetchall():
            library_root = Path(row[2]).resolve()

            # Check if file_path is within this library's root
            try:
                normalized_path.relative_to(library_root)
                # Success - this library contains the file
                return {
                    "id": row[0],
                    "name": row[1],
                    "root_path": str(library_root),
                    "is_enabled": bool(row[3]),
                    "is_default": bool(row[4]),
                    "scan_status": row[5],
                    "scan_progress": row[6],
                    "scan_total": row[7],
                    "scanned_at": row[8],
                    "scan_error": row[9],
                    "created_at": row[10],
                    "updated_at": row[11],
                }
            except ValueError:
                # Not a subpath, continue to next library
                continue

        return None

    def update_scan_status(
        self,
        library_id: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scanned_at: int | None = None,
        scan_error: str | None = None,
    ) -> None:
        """
        Update library scan status and progress.

        Args:
            library_id: Library ID
            status: Scan status ('scanning', 'complete', 'error', 'never_scanned')
            progress: Current progress (files scanned so far)
            total: Total files to scan
            scanned_at: Timestamp of last successful scan completion
            scan_error: Error message if status='error'
        """
        updates = []
        params: list[Any] = []

        if status is not None:
            updates.append("scan_status=?")
            params.append(status)
        if progress is not None:
            updates.append("scan_progress=?")
            params.append(progress)
        if total is not None:
            updates.append("scan_total=?")
            params.append(total)
        if scanned_at is not None:
            updates.append("scanned_at=?")
            params.append(scanned_at)
        if scan_error is not None:
            updates.append("scan_error=?")
            params.append(scan_error)

        if not updates:
            return  # Nothing to update

        params.append(library_id)

        self.conn.execute(f"UPDATE libraries SET {', '.join(updates)} WHERE id=?", params)
        self.conn.commit()
