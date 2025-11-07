"""
Unit tests for nomarr/data/db.py
"""

import pytest

from nomarr.data.db import Database, now_ms


@pytest.mark.unit
class TestTimestamp:
    """Test timestamp utility."""

    def test_now_ms_returns_int(self):
        """Test that now_ms() returns an integer."""
        ts = now_ms()
        assert isinstance(ts, int)

    def test_now_ms_is_milliseconds(self):
        """Test that now_ms() returns milliseconds since epoch."""
        import time

        ts = now_ms()
        current_seconds = int(time.time())

        # Should be within 1000ms of current time (allowing for test execution time)
        assert abs(ts - current_seconds * 1000) < 1000

    def test_now_ms_increases(self):
        """Test that now_ms() increases over time."""
        import time

        ts1 = now_ms()
        time.sleep(0.01)
        ts2 = now_ms()

        assert ts2 > ts1


@pytest.mark.integration
class TestDatabase:
    """Test Database database operations."""

    def test_init_creates_connection(self, temp_db):
        """Test that Database creates a connection."""
        db = Database(temp_db)
        assert db.conn is not None
        assert db.path == temp_db

    def test_init_creates_tables(self, temp_db):
        """Test that __init__ creates all required tables."""
        db = Database(temp_db)

        # Check that tables exist
        cursor = db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        assert "queue" in tables
        assert "meta" in tables
        assert "library_files" in tables
        assert "library_scans" in tables

    def test_init_idempotent(self, temp_db):
        """Test that creating DB twice with same path is safe."""
        _db1 = Database(temp_db)
        db2 = Database(temp_db)  # Should not raise

        # Verify tables still exist
        cursor = db2.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        count = cursor.fetchone()[0]
        assert count >= 4  # At least 4 tables

    def test_meta_get_set(self, temp_db):
        """Test meta key-value storage."""
        db = Database(temp_db)

        # Set a value
        db.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("test_key", "test_value"))
        db.conn.commit()

        # Get the value
        cursor = db.conn.execute("SELECT value FROM meta WHERE key = ?", ("test_key",))
        value = cursor.fetchone()[0]

        assert value == "test_value"

    def test_meta_update(self, temp_db):
        """Test updating meta values."""
        db = Database(temp_db)

        # Initial value
        db.conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("api_key", "old_key"))
        db.conn.commit()

        # Update
        db.conn.execute("UPDATE meta SET value = ? WHERE key = ?", ("new_key", "api_key"))
        db.conn.commit()

        # Verify
        cursor = db.conn.execute("SELECT value FROM meta WHERE key = ?", ("api_key",))
        value = cursor.fetchone()[0]
        assert value == "new_key"

    def test_queue_insert(self, temp_db):
        """Test inserting a job into the queue."""
        db = Database(temp_db)

        # Insert a job
        cursor = db.conn.execute(
            """
            INSERT INTO queue (path, status, created_at)
            VALUES (?, ?, ?)
            """,
            ("/music/test.mp3", "pending", now_ms()),
        )
        db.conn.commit()

        job_id = cursor.lastrowid

        # Verify
        cursor = db.conn.execute("SELECT path, status FROM queue WHERE id = ?", (job_id,))
        row = cursor.fetchone()

        assert row[0] == "/music/test.mp3"
        assert row[1] == "pending"

    def test_queue_status_update(self, temp_db):
        """Test updating job status."""
        db = Database(temp_db)

        # Insert
        cursor = db.conn.execute(
            "INSERT INTO queue (path, status, created_at) VALUES (?, ?, ?)",
            ("/music/test.mp3", "pending", now_ms()),
        )
        db.conn.commit()
        job_id = cursor.lastrowid

        # Update to running
        db.conn.execute(
            "UPDATE queue SET status = ? WHERE id = ?",
            ("running", job_id),
        )
        db.conn.commit()

        # Verify
        cursor = db.conn.execute("SELECT status FROM queue WHERE id = ?", (job_id,))
        status = cursor.fetchone()[0]
        assert status == "running"

    def test_queue_results_json(self, temp_db):
        """Test storing results JSON in queue."""
        db = Database(temp_db)

        # Insert with results
        cursor = db.conn.execute(
            """
            INSERT INTO queue (path, status, created_at, results_json)
            VALUES (?, ?, ?, ?)
            """,
            ("/music/test.mp3", "done", now_ms(), '{"genre": "rock"}'),
        )
        db.conn.commit()

        # Verify
        cursor = db.conn.execute("SELECT results_json FROM queue WHERE id = ?", (cursor.lastrowid,))
        results = cursor.fetchone()[0]
        assert results == '{"genre": "rock"}'

    def test_library_files_insert(self, temp_db):
        """Test inserting library files."""
        db = Database(temp_db)

        # Insert a file
        db.conn.execute(
            """
            INSERT INTO library_files (path, tags_json, scanned_at)
            VALUES (?, ?, ?)
            """,
            ("/music/album/song.mp3", '{"title": "Song"}', now_ms()),
        )
        db.conn.commit()

        # Verify
        cursor = db.conn.execute("SELECT tags_json FROM library_files WHERE path = ?", ("/music/album/song.mp3",))
        tags = cursor.fetchone()[0]
        assert tags == '{"title": "Song"}'

    def test_library_scans_insert(self, temp_db):
        """Test inserting library scan records."""
        db = Database(temp_db)

        # Insert a scan
        cursor = db.conn.execute(
            """
            INSERT INTO library_scans (status, started_at, files_scanned)
            VALUES (?, ?, ?)
            """,
            ("running", now_ms(), 0),
        )
        db.conn.commit()

        scan_id = cursor.lastrowid

        # Verify
        cursor = db.conn.execute("SELECT status, files_scanned FROM library_scans WHERE id = ?", (scan_id,))
        row = cursor.fetchone()
        assert row[0] == "running"
        assert row[1] == 0

    def test_queue_stats(self, temp_db):
        """Test getting queue statistics by status."""
        db = Database(temp_db)

        # Add jobs with different statuses
        db.conn.execute(
            "INSERT INTO queue (path, status) VALUES (?, ?)",
            ("/music/pending1.mp3", "pending"),
        )
        db.conn.execute(
            "INSERT INTO queue (path, status) VALUES (?, ?)",
            ("/music/pending2.mp3", "pending"),
        )
        db.conn.execute(
            "INSERT INTO queue (path, status, started_at) VALUES (?, ?, ?)",
            ("/music/running.mp3", "running", now_ms()),
        )
        db.conn.execute(
            "INSERT INTO queue (path, status, finished_at) VALUES (?, ?, ?)",
            ("/music/done.mp3", "done", now_ms()),
        )
        db.conn.execute(
            "INSERT INTO queue (path, status, finished_at, error_message) VALUES (?, ?, ?, ?)",
            ("/music/error.mp3", "error", now_ms(), "test error"),
        )
        db.conn.commit()

        # Get stats
        stats = db.queue_stats()

        # Verify counts
        assert stats["pending"] == 2
        assert stats["running"] == 1
        assert stats["done"] == 1
        assert stats["error"] == 1
