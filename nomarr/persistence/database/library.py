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
        calibration: str | None = None,
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
            calibration: Calibration metadata as JSON (dict of model_key -> calibration_id)
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
                tags_json, nom_tags, calibration, scanned_at, last_tagged_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                calibration=excluded.calibration,
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

    def mark_file_tagged(self, path: str, tagged_version: str) -> None:
        """
        Mark a file as tagged with the given version.

        Args:
            path: File path
            tagged_version: Version string of the tagger
        """
        self.conn.execute(
            "UPDATE library_files SET tagged=1, tagged_version=?, last_tagged_at=? WHERE path=?",
            (tagged_version, now_ms(), path),
        )
        self.conn.commit()

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

        # Get paginated results
        query = f"SELECT * FROM library_files {where_clause} ORDER BY artist, album, track_number LIMIT ? OFFSET ?"
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
        cur = self.conn.execute("SELECT file_path FROM library_files")
        return [row[0] for row in cur.fetchall()]

    def get_tagged_file_paths(self) -> list[str]:
        """
        Get all file paths that have been tagged (tagged=1).

        Returns:
            List of file paths that have been tagged
        """
        cur = self.conn.execute("SELECT file_path FROM library_files WHERE tagged = 1")
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

    def enqueue_scan(self, path: str, force: bool = False) -> int:
        """
        Enqueue a file for library scanning.

        Args:
            path: Path to the file to scan
            force: Whether to force rescan even if file hasn't changed

        Returns:
            Job ID
        """
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO library_queue(path, status, force, started_at) VALUES(?, 'pending', ?, NULL)",
            (path, 1 if force else 0),
        )
        self.conn.commit()
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to enqueue scan job - no row ID returned")
        return job_id

    def dequeue_scan(self) -> tuple[int, str, bool] | None:
        """
        Get next pending scan job and mark it as running.

        Returns:
            Tuple of (job_id, path, force) or None if no pending jobs
        """
        cur = self.conn.execute("SELECT id, path, force FROM library_queue WHERE status='pending' ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None

        job_id, path, force = row
        self.conn.execute("UPDATE library_queue SET status='running', started_at=? WHERE id=?", (now_ms(), job_id))
        self.conn.commit()

        return (job_id, path, bool(force))

    def mark_scan_complete(self, job_id: int) -> None:
        """
        Mark a scan job as complete.

        Args:
            job_id: Job ID to mark complete
        """
        self.conn.execute(
            "UPDATE library_queue SET status='done', completed_at=? WHERE id=?",
            (now_ms(), job_id),
        )
        self.conn.commit()

    def mark_scan_error(self, job_id: int, error: str) -> None:
        """
        Mark a scan job as failed.

        Args:
            job_id: Job ID to mark as failed
            error: Error message
        """
        self.conn.execute(
            "UPDATE library_queue SET status='error', completed_at=?, error_message=? WHERE id=?",
            (now_ms(), error, job_id),
        )
        self.conn.commit()

    def list_scan_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        List recent scan jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job dicts
        """
        cur = self.conn.execute(
            "SELECT id, path, status, force, started_at, completed_at, error_message "
            "FROM library_queue ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    def count_pending_scans(self) -> int:
        """
        Count pending scan jobs.

        Returns:
            Number of pending jobs
        """
        cur = self.conn.execute("SELECT COUNT(*) FROM library_queue WHERE status='pending'")
        row = cur.fetchone()
        return row[0] if row else 0

    def clear_scan_queue(self) -> int:
        """
        Clear all pending scan jobs.

        Returns:
            Number of jobs cleared
        """
        cur = self.conn.execute("DELETE FROM library_queue WHERE status='pending'")
        self.conn.commit()
        return cur.rowcount

    def reset_running_scans(self) -> int:
        """
        Reset any scan jobs stuck in 'running' state back to 'pending'.
        This handles container restarts where a scan was interrupted mid-processing.

        Returns:
            Number of jobs reset
        """
        cur = self.conn.execute("UPDATE library_queue SET status='pending', started_at=NULL WHERE status='running'")
        self.conn.commit()
        return cur.rowcount

    # ---------------------------- Library Queue Statistics ----------------------------

    def get_scan_queue_stats(self) -> dict[str, Any]:
        """
        Get statistics about the scan queue.

        Returns:
            Dict with pending, running, done, error counts
        """
        cur = self.conn.execute(
            """SELECT status, COUNT(*) as count
               FROM library_queue
               GROUP BY status"""
        )
        stats = {"pending": 0, "running": 0, "done": 0, "error": 0, "total": 0}
        for row in cur.fetchall():
            status, count = row
            stats[status] = count
            stats["total"] += count
        return stats

    def get_library_scan(self, scan_id: int) -> dict[str, Any] | None:
        """
        Get library scan job by ID.

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
