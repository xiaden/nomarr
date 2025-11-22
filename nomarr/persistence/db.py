import os
import sqlite3
import time

# Import operation classes
from nomarr.persistence.database.calibration import CalibrationOperations
from nomarr.persistence.database.library import LibraryOperations
from nomarr.persistence.database.meta import MetaOperations
from nomarr.persistence.database.queue import QueueOperations
from nomarr.persistence.database.sessions import SessionOperations
from nomarr.persistence.database.tags import TagOperations

# Re-export SQLite utility functions
from nomarr.persistence.database.utils import (
    count_and_delete,
    count_and_update,
    get_queue_stats,
    safe_count,
)

__all__ = [
    "SCHEMA",
    "SCHEMA_VERSION",
    "Database",
    "count_and_delete",
    "count_and_update",
    "get_queue_stats",
    "now_ms",
    "safe_count",
]


# ----------------------------------------------------------------------
#  Utility helpers
# ----------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


# ----------------------------------------------------------------------
#  Database Schema
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
        calibration TEXT,
        scanned_at INTEGER,
        last_tagged_at INTEGER,
        tagged INTEGER DEFAULT 0,
        tagged_version TEXT,
        skip_auto_tag INTEGER DEFAULT 0
    );
    """,
    # Library scan queue - tracks library scanning jobs (read existing tags from files)
    # Each row represents ONE file to scan
    """
    CREATE TABLE IF NOT EXISTS library_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        force INTEGER DEFAULT 0,
        started_at INTEGER,
        completed_at INTEGER,
        error_message TEXT
    );
    """,
    # Index for fast library queue queries
    """
    CREATE INDEX IF NOT EXISTS idx_library_queue_status ON library_queue(status);
    """,
    # Calibration queue - tracks recalibration jobs (apply calibration to existing tags)
    """
    CREATE TABLE IF NOT EXISTS calibration_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
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
# Version 2: Added calibration column to library_files
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

        # Initialize operation classes
        self.meta = MetaOperations(self.conn)
        self.queue = QueueOperations(self.conn)
        self.library = LibraryOperations(self.conn)
        self.tags = TagOperations(self.conn)
        self.sessions = SessionOperations(self.conn)
        self.calibration = CalibrationOperations(self.conn)

        # Store schema version for reference (pre-alpha: no migrations, just delete DB on schema changes)
        current_version = self.meta.get("schema_version")
        if not current_version:
            self.meta.set("schema_version", str(SCHEMA_VERSION))

    def close(self):
        """Close database connection."""
        self.conn.commit()
        self.conn.close()
