"""
Integration tests for session persistence (write-through cache pattern).
Verifies that sessions persist in DB and can be loaded back into cache.
"""

import time

import pytest

from nomarr.interfaces.api import auth
from nomarr.services.keys import _session_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear session cache before and after each test."""
    _session_cache.clear()
    yield
    _session_cache.clear()


class TestSessionPersistence:
    """Test write-through cache pattern for sessions."""

    def test_create_session_writes_to_both_cache_and_db(self, test_db, mock_key_service, monkeypatch):
        """Creating a session should write to both cache and DB."""
        # Mock app.db to use test DB
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create session
        token = auth.create_session()

        # Verify in cache
        assert token in _session_cache
        assert _session_cache[token] > time.time()

        # Verify in DB
        expiry = test_db.get_session(token)
        assert expiry is not None
        assert expiry > time.time()

        # Verify cache and DB have same expiry
        assert _session_cache[token] == expiry

    def test_invalidate_session_removes_from_both_cache_and_db(self, test_db, mock_key_service, monkeypatch):
        """Invalidating a session should remove from both cache and DB."""
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create session
        token = auth.create_session()

        # Verify exists in both
        assert token in _session_cache
        assert test_db.get_session(token) is not None

        # Invalidate
        auth.invalidate_session(token)

        # Verify removed from both
        assert token not in _session_cache
        assert test_db.get_session(token) is None

    def test_cleanup_removes_from_both_cache_and_db(self, test_db, mock_key_service, monkeypatch):
        """Cleanup should remove expired sessions from both cache and DB."""
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create an expired session manually
        expired_token = "expired_token_123"
        expired_time = time.time() - 1000  # 1000 seconds ago

        # Add to cache
        _session_cache[expired_token] = expired_time

        # Add to DB
        test_db.create_session(expired_token, expired_time)

        # Verify exists in both
        assert expired_token in _session_cache
        assert test_db.get_session(expired_token) == expired_time

        # Cleanup
        count = auth.cleanup_expired_sessions()

        # Verify removed from both
        assert expired_token not in _session_cache
        assert test_db.get_session(expired_token) is None
        assert count == 1  # Returns count from cache

    def test_load_sessions_from_db_populates_cache(self, test_db, mock_key_service, monkeypatch):
        """Loading sessions from DB should populate cache with non-expired sessions."""
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create sessions directly in DB
        valid_token = "valid_token_123"
        expired_token = "expired_token_456"

        valid_expiry = time.time() + 3600  # 1 hour in future
        expired_expiry = time.time() - 3600  # 1 hour ago

        test_db.create_session(valid_token, valid_expiry)
        test_db.create_session(expired_token, expired_expiry)

        # Cache should be empty
        assert len(_session_cache) == 0

        # Load from DB
        count = auth.load_sessions_from_db()

        # Only valid session should be loaded
        assert count == 1
        assert valid_token in _session_cache
        assert expired_token not in _session_cache
        assert _session_cache[valid_token] == valid_expiry

    def test_session_survives_cache_clear(self, test_db, mock_key_service, monkeypatch):
        """Sessions in DB can be reloaded after cache is cleared (simulates restart)."""
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create session
        token = auth.create_session()
        original_expiry = _session_cache[token]

        # Simulate server restart (clear cache)
        _session_cache.clear()

        # Verify session gone from cache
        assert token not in _session_cache

        # Reload from DB
        auth.load_sessions_from_db()

        # Verify session back in cache
        assert token in _session_cache
        assert _session_cache[token] == original_expiry

        # Verify still validates
        assert auth.validate_session(token) is True

    def test_validate_session_reads_from_cache_not_db(self, test_db, mock_key_service, monkeypatch):
        """Validation should only read from cache (fast path), not DB."""
        import nomarr.app as app

        monkeypatch.setattr(app, "db", test_db)

        # Create session
        token = auth.create_session()

        # Delete from DB but keep in cache
        test_db.delete_session(token)

        # Should still validate (reads from cache)
        assert auth.validate_session(token) is True

        # Now delete from cache too
        _session_cache.pop(token)

        # Should no longer validate
        assert auth.validate_session(token) is False
