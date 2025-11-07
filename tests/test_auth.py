"""
Tests for authentication logic (API keys, passwords, sessions).
"""

import time

import pytest

from nomarr.interfaces.api.auth import (
    cleanup_expired_sessions,
    create_session,
    get_admin_password_hash,
    get_internal_key,
    get_or_create_admin_password,
    get_or_create_api_key,
    get_or_create_internal_key,
    hash_password,
    invalidate_session,
    validate_session,
    verify_password,
)
from nomarr.services.keys import _session_cache as _sessions


class TestAPIKeys:
    def test_get_or_create_api_key_creates_new(self, test_db):
        """First call should create a new API key."""
        key = get_or_create_api_key(test_db)
        assert key
        assert isinstance(key, str)
        assert len(key) > 16  # Should be urlsafe token

    def test_get_or_create_api_key_returns_existing(self, test_db):
        """Second call should return the same key."""
        key1 = get_or_create_api_key(test_db)
        key2 = get_or_create_api_key(test_db)
        assert key1 == key2

    def test_get_or_create_internal_key_creates_new(self, test_db):
        """First call should create a new internal key."""
        key = get_or_create_internal_key(test_db)
        assert key
        assert isinstance(key, str)
        assert len(key) > 16

    def test_get_or_create_internal_key_returns_existing(self, test_db):
        """Second call should return the same key."""
        key1 = get_or_create_internal_key(test_db)
        key2 = get_or_create_internal_key(test_db)
        assert key1 == key2

    def test_get_internal_key_raises_if_missing(self, test_db):
        """get_internal_key should raise if key not found."""
        with pytest.raises(RuntimeError, match="Internal API key not found"):
            get_internal_key(test_db)

    def test_get_internal_key_returns_existing(self, test_db):
        """get_internal_key should return existing key."""
        get_or_create_internal_key(test_db)
        key = get_internal_key(test_db)
        assert key
        assert isinstance(key, str)


class TestPasswordHashing:
    def test_hash_password_returns_salt_and_hash(self):
        """hash_password should return 'salt:hash' format."""
        hashed = hash_password("testpass123")
        assert isinstance(hashed, str)
        assert ":" in hashed
        salt, pwd_hash = hashed.split(":", 1)
        assert len(salt) == 32  # 16 bytes hex = 32 chars
        assert len(pwd_hash) == 64  # SHA-256 hex = 64 chars

    def test_verify_password_correct(self):
        """verify_password should return True for correct password."""
        hashed = hash_password("correct_password")
        assert verify_password("correct_password", hashed) is True

    def test_verify_password_incorrect(self):
        """verify_password should return False for wrong password."""
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_verify_password_invalid_format(self):
        """verify_password should return False for invalid hash format."""
        assert verify_password("password", "invalid_hash") is False

    def test_different_passwords_different_hashes(self):
        """Same password should produce different hashes (different salts)."""
        hash1 = hash_password("same_password")
        hash2 = hash_password("same_password")
        assert hash1 != hash2  # Different salts


class TestAdminPassword:
    def test_get_or_create_admin_password_auto_generates(self, test_db):
        """First call should auto-generate password."""
        plaintext = get_or_create_admin_password(test_db, config_password=None)
        assert plaintext  # Should return generated password
        assert len(plaintext) > 16
        # Verify hash was stored
        password_hash = test_db.get_meta("admin_password_hash")
        assert password_hash
        assert ":" in password_hash

    def test_get_or_create_admin_password_uses_config(self, test_db):
        """First call with config_password should use it."""
        plaintext = get_or_create_admin_password(test_db, config_password="my_config_pass")
        assert plaintext == ""  # Don't return config password
        # Verify hash was stored and verifies
        password_hash = test_db.get_meta("admin_password_hash")
        assert password_hash
        assert verify_password("my_config_pass", password_hash)

    def test_get_or_create_admin_password_ignores_config_if_exists(self, test_db):
        """Second call should ignore config_password."""
        # First call with auto-generated
        get_or_create_admin_password(test_db, config_password=None)
        hash1 = test_db.get_meta("admin_password_hash")
        # Second call with config - should return empty and keep original hash
        plaintext2 = get_or_create_admin_password(test_db, config_password="new_config")
        hash2 = test_db.get_meta("admin_password_hash")
        assert plaintext2 == ""
        assert hash1 == hash2

    def test_get_admin_password_hash_raises_if_missing(self, test_db):
        """get_admin_password_hash should raise if not found."""
        with pytest.raises(RuntimeError, match="Admin password not found"):
            get_admin_password_hash(test_db)

    def test_get_admin_password_hash_returns_existing(self, test_db):
        """get_admin_password_hash should return existing hash."""
        get_or_create_admin_password(test_db, config_password="test123")
        password_hash = get_admin_password_hash(test_db)
        assert password_hash
        assert verify_password("test123", password_hash)


class TestSessionManagement:
    def setup_method(self):
        """Clear session store before each test."""
        _sessions.clear()

    def teardown_method(self):
        """Clear session store after each test."""
        _sessions.clear()

    def test_create_session_returns_token(self, mock_key_service):
        """create_session should return a session token."""
        token = create_session()
        assert token
        assert isinstance(token, str)
        assert len(token) > 16

    def test_validate_session_valid(self, mock_key_service):
        """validate_session should return True for valid token."""
        token = create_session()
        assert validate_session(token) is True

    def test_validate_session_invalid(self, mock_key_service):
        """validate_session should return False for unknown token."""
        assert validate_session("unknown_token") is False

    def test_validate_session_expired(self, mock_key_service):
        """validate_session should return False for expired token."""
        # Manually create expired session
        token = "expired_token"
        _sessions[token] = time.time() - 1  # 1 second ago
        assert validate_session(token) is False
        # Should be removed from store
        assert token not in _sessions

    def test_invalidate_session(self, mock_key_service):
        """invalidate_session should remove token."""
        token = create_session()
        invalidate_session(token)
        assert validate_session(token) is False

    def test_cleanup_expired_sessions(self, mock_key_service):
        """cleanup_expired_sessions should remove expired tokens."""
        # Create one expired and one valid session
        expired_token = "expired_token"
        _sessions[expired_token] = time.time() - 1  # 1 second ago
        valid_token = create_session()

        count = cleanup_expired_sessions()
        assert count == 1
        assert validate_session(expired_token) is False
        assert validate_session(valid_token) is True
