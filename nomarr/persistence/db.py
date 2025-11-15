import json
import os
import sqlite3
import time
from typing import Any


# ----------------------------------------------------------------------
#  Utility helpers
# ----------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


# ----------------------------------------------------------------------
#  Schema
# ----------------------------------------------------------------------
SCHEMA = [
    # Tag processing queue - tracks ML tagging jobs and errors
    """
    CREATE TABLE IF NOT EXISTS tag_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT,
        status TEXT DEFAULT 'pending',
        created_at INTEGER,
        started_at INTEGER,
        finished_at INTEGER,
        error_message TEXT,
        results_json TEXT,
        force INTEGER DEFAULT 0
    );
    """,
    # Metadata key-value store (API key, worker state, etc.)
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """,
    # Library files - tracks music library with metadata and tags
    """
    CREATE TABLE IF NOT EXISTS library_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        file_size INTEGER,
        modified_time INTEGER,
        duration_seconds REAL,
        artist TEXT,
        album TEXT,
        title TEXT,
        genre TEXT,
        year INTEGER,
        track_number INTEGER,
        tags_json TEXT,
        nom_tags TEXT,
        scanned_at INTEGER,
        last_tagged_at INTEGER,
        tagged INTEGER DEFAULT 0,
        tagged_version TEXT,
        skip_auto_tag INTEGER DEFAULT 0
    );
    """,
    # Library scan queue - tracks library scanning jobs (read existing tags from files)
    """
    CREATE TABLE IF NOT EXISTS library_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER,
        finished_at INTEGER,
        files_scanned INTEGER DEFAULT 0,
        files_added INTEGER DEFAULT 0,
        files_updated INTEGER DEFAULT 0,
        files_removed INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running',
        error_message TEXT
    );
    """,
    # Calibration queue - tracks recalibration jobs (apply calibration to existing tags)
    """
    CREATE TABLE IF NOT EXISTS calibration_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        started_at INTEGER,
        completed_at INTEGER,
        error_message TEXT
    );
    """,
    # Index for fast calibration queue queries
    """
    CREATE INDEX IF NOT EXISTS idx_calibration_queue_status ON calibration_queue(status);
    """,
    # Library tags - normalized tag storage for fast queries
    """
    CREATE TABLE IF NOT EXISTS library_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        tag_key TEXT NOT NULL,
        tag_value TEXT,
        tag_type TEXT DEFAULT 'string',
        FOREIGN KEY (file_id) REFERENCES library_files(id) ON DELETE CASCADE
    );
    """,
    # Indexes for fast tag queries
    """
    CREATE INDEX IF NOT EXISTS idx_library_tags_file_id ON library_tags(file_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_library_tags_key ON library_tags(tag_key);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_library_tags_key_value ON library_tags(tag_key, tag_value);
    """,
    # Sessions - persistent session storage for web UI
    """
    CREATE TABLE IF NOT EXISTS sessions (
        session_token TEXT PRIMARY KEY,
        expiry_timestamp REAL NOT NULL,
        created_at REAL NOT NULL
    );
    """,
    # Index for fast session expiry cleanup
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expiry_timestamp);
    """,
    # Calibration runs - tracks calibration generation and drift metrics
    """
    CREATE TABLE IF NOT EXISTS calibration_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_name TEXT NOT NULL,
        head_name TEXT NOT NULL,
        version INTEGER NOT NULL,
        file_count INTEGER NOT NULL,
        timestamp INTEGER NOT NULL,
        p5 REAL,
        p95 REAL,
        range REAL,
        reference_version INTEGER,
        apd_p5 REAL,
        apd_p95 REAL,
        srd REAL,
        jsd REAL,
        median_drift REAL,
        iqr_drift REAL,
        is_stable INTEGER DEFAULT 0,
        UNIQUE(model_name, head_name, version)
    );
    """,
    # Index for fast calibration queries
    """
    CREATE INDEX IF NOT EXISTS idx_calibration_runs_model_head ON calibration_runs(model_name, head_name);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_calibration_runs_reference ON calibration_runs(model_name, head_name, is_stable);
    """,
]

# Schema version (pre-alpha, no migrations yet - just initial schema)
SCHEMA_VERSION = 1


# ----------------------------------------------------------------------
#  Database Layer
# ----------------------------------------------------------------------
class Database:
    """
    Application database.

    Handles all data persistence: queue, library, sessions, meta config.
    Single source of truth for database operations across all services.
    """

    def __init__(self, path: str):
        self.path = path
        # Ensure parent directory exists so sqlite can create the DB file.
        # This makes initialization idempotent when `/app/config` is a bind mount
        # that may not contain a `db/` directory yet.
        db_dir = os.path.dirname(path) or "."
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception as exc:
            raise RuntimeError(f"Unable to create database directory '{db_dir}': {exc}") from exc

        try:
            self.conn = sqlite3.connect(path, check_same_thread=False)
        except sqlite3.OperationalError as exc:
            # Re-raise with a clearer message about common mount/permission issues
            raise RuntimeError(
                f"Failed to open SQLite DB at '{path}'. Ensure the directory exists and is writable by the container user: {exc}"
            ) from exc
        self.conn.execute("PRAGMA journal_mode=WAL;")
        for ddl in SCHEMA:
            self.conn.execute(ddl)
        self.conn.commit()

        # Store schema version for reference (pre-alpha: no migrations, just delete DB on schema changes)
        current_version = self.get_meta("schema_version")
        if not current_version:
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    def create_tag_scan_cache_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_scan_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                version TEXT,
                tags_strict TEXT,
                tags_regular TEXT,
                tags_loose TEXT
            )
        """)

    def insert_or_update_tag_scan(self, path, version, tags_strict, tags_regular, tags_loose):
        self.conn.execute(
            """
            INSERT INTO tag_scan_cache (path, version, tags_strict, tags_regular, tags_loose)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                version=excluded.version,
                tags_strict=excluded.tags_strict,
                tags_regular=excluded.tags_regular,
                tags_loose=excluded.tags_loose
        """,
            (path, version, tags_strict, tags_regular, tags_loose),
        )

    def get_all_tag_scans(self):
        return self.conn.execute("SELECT * FROM tag_scan_cache").fetchall()

    # ---------------------------- Meta ----------------------------
    def get_meta(self, key: str) -> str | None:
        cur = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str):
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (key, value))
        self.conn.commit()

    def delete_meta(self, key: str):
        """Delete a metadata key-value pair."""
        self.conn.execute("DELETE FROM meta WHERE key=?", (key,))
        self.conn.commit()

    # ---------------------------- Tag Queue ----------------------------
    def enqueue(self, path: str, force: bool = False) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO tag_queue(path, status, created_at, force) VALUES(?,?,?,?)",
            (path, "pending", now_ms(), int(force)),
        )
        self.conn.commit()

        # Validate successful insert and return type
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to insert job into tag_queue - no row ID returned")
        return job_id

    def update_job(
        self, job_id: int, status: str, error_message: str | None = None, results: dict[str, Any] | None = None
    ):
        ts = now_ms()
        results_json = json.dumps(results) if results else None

        if status == "running":
            self.conn.execute("UPDATE tag_queue SET status=?, started_at=? WHERE id=?", (status, ts, job_id))
        elif status in ("done", "error"):
            self.conn.execute(
                "UPDATE tag_queue SET status=?, finished_at=?, error_message=?, results_json=? WHERE id=?",
                (status, ts, error_message, results_json, job_id),
            )
        else:
            self.conn.execute("UPDATE tag_queue SET status=? WHERE id=?", (status, job_id))
        self.conn.commit()

    def job_status(self, job_id: int) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM tag_queue WHERE id=?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def queue_depth(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM tag_queue WHERE status IN ('pending', 'running')")
        return int(cur.fetchone()[0])

    def queue_stats(self) -> dict[str, int]:
        """Get counts of jobs by status."""
        cur = self.conn.execute(
            """
            SELECT status, COUNT(*) as count
            FROM tag_queue
            GROUP BY status
            """
        )
        stats = {row[0]: row[1] for row in cur.fetchall()}
        # Ensure all statuses are present (default to 0)
        for status in ("pending", "running", "done", "error"):
            stats.setdefault(status, 0)
        return stats

    def clear_old_jobs(self, max_age_hours: int = 168):
        cutoff = now_ms() - max_age_hours * 3600 * 1000
        self.conn.execute("DELETE FROM tag_queue WHERE finished_at IS NOT NULL AND finished_at < ?", (cutoff,))
        self.conn.commit()

    def reset_running_to_pending(self) -> int:
        """
        Reset any jobs in 'running' state back to 'pending'.
        Used during startup to recover orphaned jobs from crashes/restarts.
        Returns the number of jobs reset.
        """
        # Count first, then update (rowcount doesn't work reliably with SQLite)
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM tag_queue WHERE status = 'running'")
        row = count_cursor.fetchone()
        count = row[0] if row else 0
        self.conn.execute(
            "UPDATE tag_queue SET status = 'pending', started_at = NULL, error_message = NULL, finished_at = NULL WHERE status = 'running'"
        )
        self.conn.commit()
        return count

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
        Returns the file ID.
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
        """Get library file by path."""
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
        Returns (files, total_count).
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

    def delete_library_file(self, path: str):
        """Remove a file from the library."""
        self.conn.execute("DELETE FROM library_files WHERE path=?", (path,))
        self.conn.commit()

    def clear_library_data(self):
        """Clear all library files, tags, and scans (keeps tag_queue and meta)."""
        self.conn.execute("DELETE FROM library_tags")
        self.conn.execute("DELETE FROM library_files")
        self.conn.execute("DELETE FROM library_queue")
        self.conn.commit()

    def get_library_stats(self) -> dict[str, Any]:
        """Get library statistics."""
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
        """Start a new library scan. Returns scan ID."""
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
    ):
        """Update library scan progress."""
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

    # ---------------------------- Calibration Queue ----------------------------
    def enqueue_calibration(self, file_path: str) -> int:
        """Add file to calibration queue. Returns calibration job ID."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO calibration_queue(file_path, status, started_at) VALUES(?, 'pending', ?)",
            (file_path, now_ms()),
        )
        self.conn.commit()
        job_id = cur.lastrowid
        if job_id is None:
            raise RuntimeError("Failed to enqueue calibration - no row ID returned")
        return job_id

    def get_next_calibration_job(self) -> tuple[int, str] | None:
        """
        Get next pending calibration job and mark it running.

        Returns:
            (job_id, file_path) or None if no jobs pending
        """
        cur = self.conn.execute(
            "SELECT id, file_path FROM calibration_queue WHERE status='pending' ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None

        job_id, file_path = row
        self.conn.execute(
            "UPDATE calibration_queue SET status='running' WHERE id=?",
            (job_id,),
        )
        self.conn.commit()
        return (job_id, file_path)

    def complete_calibration_job(self, job_id: int) -> None:
        """Mark calibration job as completed."""
        self.conn.execute(
            "UPDATE calibration_queue SET status='done', completed_at=? WHERE id=?",
            (now_ms(), job_id),
        )
        self.conn.commit()

    def fail_calibration_job(self, job_id: int, error_message: str) -> None:
        """Mark calibration job as failed."""
        self.conn.execute(
            "UPDATE calibration_queue SET status='error', completed_at=?, error_message=? WHERE id=?",
            (now_ms(), error_message, job_id),
        )
        self.conn.commit()

    def get_calibration_status(self) -> dict[str, int]:
        """
        Get calibration queue status counts.

        Returns:
            {"pending": count, "running": count, "done": count, "error": count}
        """
        cursor = self.conn.execute("SELECT status, COUNT(*) FROM calibration_queue GROUP BY status")
        counts = {"pending": 0, "running": 0, "done": 0, "error": 0}
        for status, count in cursor.fetchall():
            counts[status] = count
        return counts

    def clear_calibration_queue(self) -> int:
        """Clear all completed/failed calibration jobs. Returns number cleared."""
        cur = self.conn.execute("DELETE FROM calibration_queue WHERE status IN ('done', 'error')")
        self.conn.commit()
        return cur.rowcount

    def reset_running_calibration_jobs(self) -> int:
        """Reset stuck 'running' calibration jobs back to 'pending'. Returns count reset."""
        cur = self.conn.execute("UPDATE calibration_queue SET status='pending' WHERE status='running'")
        self.conn.commit()
        return cur.rowcount

    # ---------------------------- Library Tags ----------------------------
    def upsert_file_tags(self, file_id: int, tags: dict[str, Any]) -> None:
        """
        Replace all tags for a file with new tags.
        Deletes existing tags and inserts new ones.

        Args:
            file_id: Library file ID
            tags: Dict of tag_key -> tag_value
        """
        # Delete existing tags for this file
        self.conn.execute("DELETE FROM library_tags WHERE file_id=?", (file_id,))

        # Insert new tags
        for tag_key, tag_value in tags.items():
            # Detect tag type
            if isinstance(tag_value, list):
                tag_type = "array"
                # Store arrays as JSON
                tag_value_str = json.dumps(tag_value, ensure_ascii=False)
            elif isinstance(tag_value, float):
                tag_type = "float"
                tag_value_str = str(tag_value)
            elif isinstance(tag_value, int):
                tag_type = "int"
                tag_value_str = str(tag_value)
            else:
                tag_type = "string"
                tag_value_str = str(tag_value)

            self.conn.execute(
                """
                INSERT INTO library_tags (file_id, tag_key, tag_value, tag_type)
                VALUES (?, ?, ?, ?)
                """,
                (file_id, tag_key, tag_value_str, tag_type),
            )

        self.conn.commit()

    def get_unique_tag_keys(self) -> list[str]:
        """Get all unique tag keys across the library."""
        cursor = self.conn.execute("SELECT DISTINCT tag_key FROM library_tags ORDER BY tag_key")
        return [row[0] for row in cursor.fetchall()]

    def get_tag_values(self, tag_key: str, limit: int = 1000) -> list[tuple[str, str]]:
        """
        Get all values for a specific tag key.

        Returns:
            List of (tag_value, tag_type) tuples
        """
        cursor = self.conn.execute(
            "SELECT tag_value, tag_type FROM library_tags WHERE tag_key=? LIMIT ?", (tag_key, limit)
        )
        return cursor.fetchall()

    def get_file_tags(self, file_id: int) -> dict[str, Any]:
        """
        Get all tags for a specific file.

        Returns:
            Dict of tag_key -> tag_value (with arrays parsed from JSON)
        """
        cursor = self.conn.execute("SELECT tag_key, tag_value, tag_type FROM library_tags WHERE file_id=?", (file_id,))

        tags = {}
        for tag_key, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    tags[tag_key] = json.loads(tag_value)
                except json.JSONDecodeError:
                    tags[tag_key] = tag_value
            elif tag_type == "float":
                tags[tag_key] = float(tag_value)
            elif tag_type == "int":
                tags[tag_key] = int(tag_value)
            else:
                tags[tag_key] = tag_value

        return tags

    def get_tag_type_stats(self, tag_key: str) -> dict[str, Any]:
        """
        Get statistics about a tag's type usage.

        Returns:
            Dict with: is_multivalue (bool), sample_values (list), total_count (int)
        """
        cursor = self.conn.execute("SELECT tag_value, tag_type FROM library_tags WHERE tag_key=? LIMIT 100", (tag_key,))

        rows = cursor.fetchall()
        if not rows:
            return {"is_multivalue": False, "sample_values": [], "total_count": 0}

        types = {row[1] for row in rows}
        is_multivalue = "array" in types
        sample_values = [row[0] for row in rows[:10]]

        # Get total count
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM library_tags WHERE tag_key=?", (tag_key,))
        total_count = count_cursor.fetchone()[0]

        return {"is_multivalue": is_multivalue, "sample_values": sample_values, "total_count": total_count}

    def get_tag_summary(self, tag_key: str) -> dict[str, Any]:
        """
        Get a useful summary of tag values (for Navidrome preview).

        For string tags: returns all unique values with counts (case-insensitive grouping)
        For float/int tags: returns min, max, average
        For array tags: flattens all values and returns unique values with counts

        Returns:
            Dict with: type, is_multivalue, summary (str or dict), total_count (int)
        """
        import json

        # Get total count and detect type from sample
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM library_tags WHERE tag_key=?", (tag_key,))
        total_count = count_cursor.fetchone()[0]

        if total_count == 0:
            return {"type": "string", "is_multivalue": False, "summary": "No data", "total_count": 0}

        # Detect type from sample
        type_cursor = self.conn.execute(
            "SELECT DISTINCT tag_type FROM library_tags WHERE tag_key=? LIMIT 10", (tag_key,)
        )
        types = {row[0] for row in type_cursor}
        is_multivalue = "array" in types
        detected_type = "float" if "float" in types else "int" if "int" in types else "string"

        # Generate summary based on type (using efficient SQL queries)
        if is_multivalue:
            # For arrays (mood tags), fetch and parse JSON to count individual values
            cursor = self.conn.execute("SELECT tag_value FROM library_tags WHERE tag_key=? LIMIT 10000", (tag_key,))
            value_counts: dict[str, int] = {}

            for row in cursor:
                try:
                    # Parse JSON array - decode bytes to string first
                    raw_value = row[0]
                    if isinstance(raw_value, bytes):
                        raw_value = raw_value.decode("utf-8")
                    values = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
                    if isinstance(values, list):
                        for val in values:
                            # Count individual mood values (not combinations)
                            val_str = str(val).strip()
                            value_counts[val_str] = value_counts.get(val_str, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # Sort by count descending
            sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
            summary: dict[str, Any] | str = dict(sorted_values)

        elif detected_type in ("float", "int"):
            # Use SQL aggregation for numeric tags (much faster!)
            cursor = self.conn.execute(
                """
                SELECT
                    MIN(CAST(tag_value AS REAL)) as min_val,
                    MAX(CAST(tag_value AS REAL)) as max_val,
                    AVG(CAST(tag_value AS REAL)) as avg_val
                FROM library_tags
                WHERE tag_key=?
                """,
                (tag_key,),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                summary = {"min": row[0], "max": row[1], "avg": row[2]}
            else:
                summary = "No valid numeric values"

        else:
            # String tags: use SQL GROUP BY with case-insensitive grouping
            # Also handle mood tags stored as delimited strings (legacy format)
            cursor = self.conn.execute(
                """
                SELECT tag_value, COUNT(*) as count
                FROM library_tags
                WHERE tag_key=?
                GROUP BY tag_value COLLATE NOCASE
                ORDER BY count DESC
                """,
                (tag_key,),
            )

            # Check if this might be a delimited mood tag
            first_value = None
            all_rows = []
            for row in cursor:
                all_rows.append(row)
                if first_value is None:
                    first_value = row[0]

            # If values contain "/" separators, it's a mood tag stored as delimited string
            if first_value and ("/" in str(first_value) or ";" in str(first_value)):
                # Parse delimited mood values and count individual moods
                value_counts = {}
                for tag_value, count in all_rows:
                    try:
                        # Split on common delimiters
                        if "/" in str(tag_value):
                            moods = str(tag_value).split("/")
                        elif ";" in str(tag_value):
                            moods = str(tag_value).split(";")
                        else:
                            moods = [str(tag_value)]

                        for mood in moods:
                            mood = mood.strip()
                            if mood:
                                value_counts[mood] = value_counts.get(mood, 0) + count
                    except Exception:
                        continue

                # Sort by count descending
                sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
                summary = dict(sorted_values)
            else:
                # Regular string tag - just use the grouped counts
                summary = {row[0].lower(): row[1] for row in all_rows}

        return {"type": detected_type, "is_multivalue": is_multivalue, "summary": summary, "total_count": total_count}

    def get_library_scan(self, scan_id: int) -> dict[str, Any] | None:
        """Get library scan by ID."""
        cur = self.conn.execute("SELECT * FROM library_queue WHERE id=?", (scan_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def list_library_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent library scans."""
        cur = self.conn.execute("SELECT * FROM library_queue ORDER BY started_at DESC LIMIT ?", (limit,))
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    # ---------------------------- Sessions ----------------------------
    def create_session(self, session_token: str, expiry: float) -> None:
        """
        Insert a new session into the database.

        Args:
            session_token: Unique session token
            expiry: Expiry timestamp (Unix time)
        """
        import time

        self.conn.execute(
            "INSERT INTO sessions (session_token, expiry_timestamp, created_at) VALUES (?, ?, ?)",
            (session_token, expiry, time.time()),
        )
        self.conn.commit()

    def get_session(self, session_token: str) -> float | None:
        """
        Get session expiry timestamp from database.

        Args:
            session_token: Session token to look up

        Returns:
            Expiry timestamp if found, None otherwise
        """
        cur = self.conn.execute("SELECT expiry_timestamp FROM sessions WHERE session_token=?", (session_token,))
        row = cur.fetchone()
        return row[0] if row else None

    def delete_session(self, session_token: str) -> None:
        """
        Delete a session from the database.

        Args:
            session_token: Session token to delete
        """
        self.conn.execute("DELETE FROM sessions WHERE session_token=?", (session_token,))
        self.conn.commit()

    def load_all_sessions(self) -> dict[str, float]:
        """
        Load all non-expired sessions from database into memory.

        Returns:
            Dict mapping session_token to expiry_timestamp
        """
        import time

        now = time.time()
        cur = self.conn.execute(
            "SELECT session_token, expiry_timestamp FROM sessions WHERE expiry_timestamp > ?", (now,)
        )
        return {row[0]: row[1] for row in cur.fetchall()}

    def cleanup_expired_sessions(self) -> int:
        """
        Delete all expired sessions from database.

        Returns:
            Number of sessions deleted
        """
        import time

        now = time.time()
        cur = self.conn.execute("DELETE FROM sessions WHERE expiry_timestamp <= ?", (now,))
        self.conn.commit()
        return cur.rowcount

    # ---------------------------- Calibration Runs ----------------------------
    def insert_calibration_run(
        self,
        model_name: str,
        head_name: str,
        version: int,
        file_count: int,
        p5: float,
        p95: float,
        range_val: float,
        reference_version: int | None = None,
        apd_p5: float | None = None,
        apd_p95: float | None = None,
        srd: float | None = None,
        jsd: float | None = None,
        median_drift: float | None = None,
        iqr_drift: float | None = None,
        is_stable: bool = False,
    ) -> int:
        """
        Insert a new calibration run record.

        Args:
            model_name: Model identifier (e.g., 'effnet')
            head_name: Head identifier (e.g., 'mood_happy')
            version: Calibration version number
            file_count: Number of files used for calibration
            p5: 5th percentile value
            p95: 95th percentile value
            range_val: P95 - P5 (scale range)
            reference_version: Version this was compared against (None if first)
            apd_p5: Absolute percentile drift for P5
            apd_p95: Absolute percentile drift for P95
            srd: Scale range drift
            jsd: Jensen-Shannon divergence
            median_drift: Median drift
            iqr_drift: IQR drift
            is_stable: Whether this calibration is stable

        Returns:
            Row ID of inserted record
        """
        cur = self.conn.execute(
            """
            INSERT INTO calibration_runs (
                model_name, head_name, version, file_count, timestamp,
                p5, p95, range, reference_version,
                apd_p5, apd_p95, srd, jsd, median_drift, iqr_drift, is_stable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_name,
                head_name,
                version,
                file_count,
                now_ms(),
                p5,
                p95,
                range_val,
                reference_version,
                apd_p5,
                apd_p95,
                srd,
                jsd,
                median_drift,
                iqr_drift,
                1 if is_stable else 0,
            ),
        )
        self.conn.commit()
        row_id = cur.lastrowid
        if row_id is None:
            raise RuntimeError("Failed to insert calibration run - no row ID returned")
        return row_id

    def get_latest_calibration_run(self, model_name: str, head_name: str) -> dict[str, Any] | None:
        """
        Get the most recent calibration run for a model/head.

        Args:
            model_name: Model identifier
            head_name: Head identifier

        Returns:
            Calibration run dict or None if no runs exist
        """
        cur = self.conn.execute(
            """
            SELECT * FROM calibration_runs
            WHERE model_name=? AND head_name=?
            ORDER BY version DESC
            LIMIT 1
            """,
            (model_name, head_name),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def get_reference_calibration_run(self, model_name: str, head_name: str) -> dict[str, Any] | None:
        """
        Get the current reference (stable) calibration run for a model/head.

        The reference is the most recent stable calibration that new runs are compared against.

        Args:
            model_name: Model identifier
            head_name: Head identifier

        Returns:
            Reference calibration run dict or None if no stable runs exist
        """
        cur = self.conn.execute(
            """
            SELECT * FROM calibration_runs
            WHERE model_name=? AND head_name=? AND is_stable=1
            ORDER BY version DESC
            LIMIT 1
            """,
            (model_name, head_name),
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row, strict=False))

    def list_calibration_runs(
        self, model_name: str | None = None, head_name: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """
        List calibration runs with optional filtering.

        Args:
            model_name: Filter by model (optional)
            head_name: Filter by head (optional)
            limit: Maximum number of results

        Returns:
            List of calibration run dicts, ordered by timestamp DESC
        """
        where_clauses = []
        params: list[Any] = []

        if model_name:
            where_clauses.append("model_name=?")
            params.append(model_name)
        if head_name:
            where_clauses.append("head_name=?")
            params.append(head_name)

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
        params.append(limit)

        cur = self.conn.execute(
            f"SELECT * FROM calibration_runs WHERE {where_clause} ORDER BY timestamp DESC LIMIT ?", params
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]

    # ---------------------------- Cleanup ----------------------------
    def close(self):
        self.conn.commit()
        self.conn.close()
