"""Library files operations for the library_files table."""

import sqlite3
from typing import Any

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class LibraryFilesOperations:
    """Operations for the library_files table (music library metadata and tags)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_library_file(
        self,
        path: LibraryPath,
        library_id: int,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        calibration: str | None = None,
        last_tagged_at: int | None = None,
    ) -> int:
        """
        Insert or update a library file entry.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            library_id: ID of owning library
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            calibration: Calibration metadata as JSON (dict of model_key -> calibration_id)
            last_tagged_at: Last tagging timestamp

        Returns:
            File ID

        Raises:
            ValueError: If path status is not "valid"
        """
        if not path.is_valid():
            raise ValueError(f"Cannot upsert invalid path ({path.status}): {path.reason}")

        scanned_at = now_ms()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO library_files(
                path, library_id, file_size, modified_time, duration_seconds,
                artist, album, title,
                calibration, scanned_at, last_tagged_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                library_id=excluded.library_id,
                file_size=excluded.file_size,
                modified_time=excluded.modified_time,
                duration_seconds=excluded.duration_seconds,
                artist=excluded.artist,
                album=excluded.album,
                title=excluded.title,
                calibration=excluded.calibration,
                scanned_at=excluded.scanned_at,
                last_tagged_at=COALESCE(excluded.last_tagged_at, last_tagged_at)
            """,
            (
                str(path.absolute),
                library_id,
                file_size,
                modified_time,
                duration_seconds,
                artist,
                album,
                title,
                calibration,
                scanned_at,
                last_tagged_at,
            ),
        )
        self.conn.commit()
        file_id = cur.lastrowid
        if file_id is None:
            raise RuntimeError("Failed to upsert library file - no row ID returned")
        return file_id

    def mark_file_tagged(self, path: LibraryPath, tagged_version: str) -> None:
        """
        Mark a file as tagged with the given version.

        Args:
            path: LibraryPath with validated file path
            tagged_version: Version string of the tagger
        """
        if not path.is_valid():
            raise ValueError(f"Cannot mark invalid path as tagged ({path.status}): {path.reason}")

        self.conn.execute(
            "UPDATE library_files SET tagged=1, tagged_version=?, last_tagged_at=? WHERE path=?",
            (tagged_version, now_ms(), str(path.absolute)),
        )
        self.conn.commit()

    def get_file_by_id(self, file_id: int) -> dict[str, Any] | None:
        """
        Get library file by ID.

        Args:
            file_id: File ID

        Returns:
            File dict or None if not found. Calibration is parsed from JSON.
        """
        import json

        cur = self.conn.execute("SELECT * FROM library_files WHERE id=?", (file_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        file_dict = dict(zip(columns, row, strict=False))

        # Parse calibration JSON (default to empty dict if null/invalid)
        calib_json = file_dict.get("calibration")
        if calib_json:
            try:
                file_dict["calibration"] = json.loads(calib_json)
            except Exception:
                file_dict["calibration"] = {}
        else:
            file_dict["calibration"] = {}

        return file_dict

    def get_library_file(self, path: str) -> dict[str, Any] | None:
        """
        Get library file by path.

        Args:
            path: File path

        Returns:
            File dict or None if not found. Calibration is parsed from JSON.
        """
        import json

        cur = self.conn.execute("SELECT * FROM library_files WHERE path=?", (path,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        file_dict = dict(zip(columns, row, strict=False))

        # Parse calibration JSON (default to empty dict if null/invalid)
        calib_json = file_dict.get("calibration")
        if calib_json:
            try:
                file_dict["calibration"] = json.loads(calib_json)
            except Exception:
                file_dict["calibration"] = {}
        else:
            file_dict["calibration"] = {}

        return file_dict

    def get_file_modified_times(self) -> dict[str, int]:
        """
        Get all file paths and their modified times in one query.

        Returns:
            Dict mapping file path to modified_time (milliseconds)
        """
        cur = self.conn.execute("SELECT path, modified_time FROM library_files")
        return {row[0]: row[1] for row in cur.fetchall()}

    def list_library_files(
        self, limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """
        List library files with optional filtering.

        Args:
            limit: Maximum number of files to return
            offset: Number of files to skip
            artist: Filter by artist name
            album: Filter by album name

        Returns:
            Tuple of (files list, total count). Calibration is parsed from JSON for each file.
        """
        import json

        where_clause = ""
        params: list[Any] = []

        if artist:
            where_clause = "WHERE artist = ?"
            params.append(artist)
        elif album:
            where_clause = "WHERE album = ?"
            params.append(album)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM library_files {where_clause}"
        total = int(self.conn.execute(count_query, params).fetchone()[0])

        # Get paginated results (sort by artist, album, title since track_number moved to tags)
        query = f"SELECT * FROM library_files {where_clause} ORDER BY artist, album, title LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = self.conn.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        files = []
        for row in cur.fetchall():
            file_dict = dict(zip(columns, row, strict=False))
            # Parse calibration JSON (default to empty dict if null/invalid)
            calib_json = file_dict.get("calibration")
            if calib_json:
                try:
                    file_dict["calibration"] = json.loads(calib_json)
                except Exception:
                    file_dict["calibration"] = {}
            else:
                file_dict["calibration"] = {}
            files.append(file_dict)

        return files, total

    def get_all_library_paths(self) -> list[str]:
        """
        Get all library file paths.

        Returns:
            List of file paths
        """
        cur = self.conn.execute("SELECT path FROM library_files")
        return [row[0] for row in cur.fetchall()]

    def get_tagged_file_paths(self) -> list[str]:
        """
        Get all file paths that have been tagged (tagged=1).

        Returns:
            List of file paths that have been tagged
        """
        cur = self.conn.execute("SELECT path FROM library_files WHERE tagged = 1")
        return [row[0] for row in cur.fetchall()]

    def delete_library_file(self, path: str) -> None:
        """
        Remove a file from the library.

        Args:
            path: File path to delete
        """
        self.conn.execute("DELETE FROM library_files WHERE path=?", (path,))
        self.conn.commit()

    def get_library_stats(self) -> dict[str, Any]:
        """
        Get library statistics.

        Returns:
            Dict with: total_files, total_artists, total_albums, total_duration, total_size
        """
        cur = self.conn.execute(
            """
            SELECT
                COUNT(*) as total_files,
                COUNT(DISTINCT artist) as total_artists,
                COUNT(DISTINCT album) as total_albums,
                SUM(duration_seconds) as total_duration,
                SUM(file_size) as total_size
            FROM library_files
            """
        )
        row = cur.fetchone()
        if not row:
            return {}
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def clear_library_data(self) -> None:
        """
        Clear all library files, tags, and scans (keeps tag_queue and meta).

        WARNING: This is a cross-table operation that deletes from:
        - file_tags
        - library_files
        """
        self.conn.execute("DELETE FROM file_tags")
        self.conn.execute("DELETE FROM library_files")
        self.conn.commit()

    def batch_upsert_library_files(self, files: list[dict[str, Any]]) -> None:
        """
        Insert or update multiple library files in one transaction.

        Args:
            files: List of file dicts with keys:
                - path (str)
                - library_id (int)
                - metadata (dict)
                - file_size (int)
                - modified_time (int)
                - needs_tagging (bool)
                - is_valid (bool)
                - scanned_at (int)
        """

        for file_data in files:
            metadata = file_data.get("metadata", {})
            self.conn.execute(
                """
                INSERT INTO library_files (
                    path, library_id, file_size, modified_time,
                    duration_seconds, artist, album, title,
                    needs_tagging, is_valid, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    library_id=excluded.library_id,
                    file_size=excluded.file_size,
                    modified_time=excluded.modified_time,
                    duration_seconds=excluded.duration_seconds,
                    artist=excluded.artist,
                    album=excluded.album,
                    title=excluded.title,
                    needs_tagging=excluded.needs_tagging,
                    is_valid=excluded.is_valid,
                    scanned_at=excluded.scanned_at
                """,
                (
                    file_data["path"],
                    file_data["library_id"],
                    file_data["file_size"],
                    file_data["modified_time"],
                    metadata.get("duration"),
                    metadata.get("artist"),
                    metadata.get("album"),
                    metadata.get("title"),
                    int(file_data["needs_tagging"]),
                    int(file_data["is_valid"]),
                    file_data["scanned_at"],
                ),
            )
        self.conn.commit()

    def mark_file_invalid(self, path: str) -> None:
        """
        Mark file as no longer existing on disk.

        Args:
            path: File path to mark invalid
        """
        self.conn.execute("UPDATE library_files SET is_valid=0 WHERE path=?", (path,))
        self.conn.commit()

    def bulk_mark_invalid(self, paths: list[str]) -> None:
        """
        Mark multiple files as invalid in one operation.

        Args:
            paths: List of file paths to mark invalid
        """
        if not paths:
            return

        placeholders = ",".join("?" * len(paths))
        self.conn.execute(f"UPDATE library_files SET is_valid=0 WHERE path IN ({placeholders})", paths)
        self.conn.commit()

    def update_file_path(self, old_path: str, new_path: str, file_size: int, modified_time: int) -> None:
        """
        Update file path and metadata (for moved files).

        Args:
            old_path: Original file path
            new_path: New file path
            file_size: File size in bytes
            modified_time: Last modified timestamp
        """
        self.conn.execute(
            "UPDATE library_files SET path=?, file_size=?, modified_time=?, is_valid=1 WHERE path=?",
            (new_path, file_size, modified_time, old_path),
        )
        self.conn.commit()

    def library_has_tagged_files(self, library_id: int) -> bool:
        """
        Check if library has any files with ML tags (for conditional move detection).

        Args:
            library_id: Library ID

        Returns:
            True if library has at least one tagged file
        """
        cur = self.conn.execute("SELECT COUNT(*) FROM library_files WHERE library_id=? AND tagged=1", (library_id,))
        result = cur.fetchone()
        count: int = result[0] if result else 0
        return count > 0

    def get_files_needing_tagging(self, library_id: int | None, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Get files that need ML tagging (needs_tagging=True, is_valid=True).

        Args:
            library_id: Library ID (or None for all libraries)
            paths: Optional specific file paths to filter

        Returns:
            List of file dicts needing tagging
        """
        query = "SELECT * FROM library_files WHERE needs_tagging=1 AND is_valid=1"
        params: list = []

        if library_id is not None:
            query += " AND library_id=?"
            params.append(library_id)

        if paths:
            placeholders = ",".join("?" * len(paths))
            query += f" AND path IN ({placeholders})"
            params.extend(paths)

        cur = self.conn.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def get_files_by_chromaprint(self, chromaprint: str, library_id: int | None = None) -> list[dict[str, Any]]:
        """
        Get library files matching a chromaprint.

        Used for move detection: when a new file is found with a chromaprint,
        check if any existing files have the same chromaprint (same audio content).

        Args:
            chromaprint: Audio fingerprint hash to search for
            library_id: Optional library ID to restrict search

        Returns:
            List of file dicts with matching chromaprint (id, path, chromaprint, etc.)
        """
        query = "SELECT * FROM library_files WHERE chromaprint=?"
        params: list[Any] = [chromaprint]

        if library_id is not None:
            query += " AND library_id=?"
            params.append(library_id)

        cur = self.conn.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
