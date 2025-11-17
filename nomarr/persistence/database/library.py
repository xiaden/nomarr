"""Library operations for library_files and library_queue tables."""

import sqlite3
from typing import Any


def now_ms() -> int:
    """Get current timestamp in milliseconds."""
    import time

    return int(time.time() * 1000)


class LibraryOperations:
    """Operations for library_files (music library) and library_queue (scan tracking) tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---------------------------- Library Files ----------------------------

    def upsert_library_file(
        self,
        path: str,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        genre: str | None = None,
        year: int | None = None,
        track_number: int | None = None,
        tags_json: str | None = None,
        nom_tags: str | None = None,
        last_tagged_at: int | None = None,
    ) -> int:
        """
        Insert or update a library file entry.

        Args:
            path: File path
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            genre: Genre
            year: Release year
            track_number: Track number
            tags_json: All tags as JSON
            nom_tags: Nomarr-specific tags as JSON
            last_tagged_at: Last tagging timestamp

        Returns:
            File ID
        """
        scanned_at = now_ms()
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO library_files(
                path, file_size, modified_time, duration_seconds,
                artist, album, title, genre, year, track_number,
                tags_json, nom_tags, scanned_at, last_tagged_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                file_size=excluded.file_size,
                modified_time=excluded.modified_time,
                duration_seconds=excluded.duration_seconds,
                artist=excluded.artist,
                album=excluded.album,
                title=excluded.title,
                genre=excluded.genre,
                year=excluded.year,
                track_number=excluded.track_number,
                tags_json=excluded.tags_json,
                nom_tags=excluded.nom_tags,
                scanned_at=excluded.scanned_at,
                last_tagged_at=COALESCE(excluded.last_tagged_at, last_tagged_at)
            """,
            (
                path,
                file_size,
                modified_time,
                duration_seconds,
                artist,
                album,
                title,
                genre,
                year,
                track_number,
                tags_json,
                nom_tags,
                scanned_at,
                last_tagged_at,
            ),
        )
        self.conn.commit()
        file_id = cur.lastrowid
        if file_id is None:
            raise RuntimeError("Failed to upsert library file - no row ID returned")
        return file_id

    def get_library_file(self, path: str) -> dict[str, Any] | None:
        """
        Get library file by path.

        Args:
            path: File path

        Returns:
            File dict or None if not found
        """
        cur = self.conn.execute("SELECT * FROM library_files WHERE path=?", (path,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

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
            Tuple of (files list, total count)
        """
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

        # Get paginated results
        query = f"SELECT * FROM library_files {where_clause} ORDER BY artist, album, track_number LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = self.conn.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        files = [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

        return files, total

    def get_all_library_paths(self) -> list[str]:
        """
        Get all library file paths.

        Returns:
            List of file paths
        """
        cur = self.conn.execute("SELECT file_path FROM library_files")
        return [row[0] for row in cur.fetchall()]

    def delete_library_file(self, path: str) -> None:
        """
        Remove a file from the library.

        Args:
            path: File path to delete
        """
        self.conn.execute("DELETE FROM library_files WHERE path=?", (path,))
        self.conn.commit()

    def clear_library_data(self) -> None:
        """Clear all library files, tags, and scans (keeps tag_queue and meta)."""
        self.conn.execute("DELETE FROM library_tags")
        self.conn.execute("DELETE FROM library_files")
        self.conn.execute("DELETE FROM library_queue")
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

    # ---------------------------- Library Scan Queue ----------------------------

    def create_library_scan(self) -> int:
        """
        Start a new library scan.

        Returns:
            Scan ID
        """
        cur = self.conn.cursor()
        # Create scan in 'pending' status - worker will mark it 'running' when it starts
        cur.execute("INSERT INTO library_queue(started_at, status) VALUES(?, 'pending')", (now_ms(),))
        self.conn.commit()
        scan_id = cur.lastrowid
        if scan_id is None:
            raise RuntimeError("Failed to create library scan - no row ID returned")
        return scan_id

    def update_library_scan(
        self,
        scan_id: int,
        status: str | None = None,
        files_scanned: int | None = None,
        files_added: int | None = None,
        files_updated: int | None = None,
        files_removed: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Update library scan progress.

        Args:
            scan_id: Scan ID to update
            status: New status ('pending', 'running', 'done', 'error')
            files_scanned: Total files scanned
            files_added: Files added
            files_updated: Files updated
            files_removed: Files removed
            error_message: Error message if status is 'error'
        """
        updates = []
        params: list[str | int] = []

        if status:
            updates.append("status=?")
            params.append(status)
            if status in ("done", "error"):
                updates.append("finished_at=?")
                params.append(now_ms())

        if files_scanned is not None:
            updates.append("files_scanned=?")
            params.append(files_scanned)
        if files_added is not None:
            updates.append("files_added=?")
            params.append(files_added)
        if files_updated is not None:
            updates.append("files_updated=?")
            params.append(files_updated)
        if files_removed is not None:
            updates.append("files_removed=?")
            params.append(files_removed)
        if error_message:
            updates.append("error_message=?")
            params.append(error_message)

        if updates:
            params.append(scan_id)
            query = f"UPDATE library_queue SET {', '.join(updates)} WHERE id=?"
            self.conn.execute(query, params)
            self.conn.commit()

    def get_library_scan(self, scan_id: int) -> dict[str, Any] | None:
        """
        Get library scan by ID.

        Args:
            scan_id: Scan ID to look up

        Returns:
            Scan dict or None if not found
        """
        cur = self.conn.execute("SELECT * FROM library_queue WHERE id=?", (scan_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def list_library_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        List recent library scans.

        Args:
            limit: Maximum number of scans to return

        Returns:
            List of scan dicts, ordered by started_at DESC
        """
        cur = self.conn.execute("SELECT * FROM library_queue ORDER BY started_at DESC LIMIT ?", (limit,))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def reset_running_library_scans(self) -> int:
        """
        Reset any library scans stuck in 'running' state back to 'pending'.
        This handles container restarts where a scan was interrupted mid-processing.

        Returns:
            Number of scans reset
        """
        cur = self.conn.execute("UPDATE library_queue SET status='pending' WHERE status='running'")
        self.conn.commit()
        return cur.rowcount
