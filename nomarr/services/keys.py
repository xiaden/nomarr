"""
Key Management Service

Centralized service for managing authentication credentials:
- Public API keys (for Lidarr/external integrations)
- Internal API keys (for CLI access)
- Admin passwords (for web UI authentication)
- Session tokens (for web UI session management)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time

from nomarr.data.db import Database

# Session timeout (24 hours)
SESSION_TIMEOUT_SECONDS = 86400

# In-memory session cache to avoid DB hits on every request
# Format: {token: expiry_timestamp}
_session_cache: dict[str, float] = {}


class KeyManagementService:
    """Service for managing API keys, passwords, and sessions."""

    def __init__(self, db: Database):
        """
        Initialize the key management service.

        Args:
            db: Database instance for persistence
        """
        self.db = db

    # ----------------------------------------------------------------------
    # Public API Key Management
    # ----------------------------------------------------------------------

    def get_api_key(self) -> str:
        """
        Get the public API key (raises if not found).

        Returns:
            API key string

        Raises:
            RuntimeError: If API key not found in database
        """
        key = self.db.get_meta("api_key")
        if not key:
            raise RuntimeError("API key not found in DB. Key should be generated during initialization.")
        return key

    def get_or_create_api_key(self) -> str:
        """
        Get or create the public API key for external endpoints.
        This key is used by Lidarr and other external integrations.

        Returns:
            API key string (existing or newly generated)
        """
        key = self.db.get_meta("api_key")
        if key:
            return key
        new_key = secrets.token_urlsafe(32)
        self.db.set_meta("api_key", new_key)
        logging.info("[KeyManagement] Generated new API key on first run.")
        return new_key

    def rotate_api_key(self) -> str:
        """
        Generate a new API key, replacing any existing one.

        Returns:
            New API key string

        Warning:
            This invalidates the old key immediately. All services using
            the old key will need to be updated.
        """
        new_key = secrets.token_urlsafe(32)
        self.db.set_meta("api_key", new_key)
        logging.warning("[KeyManagement] API key rotated - old key invalidated")
        return new_key

    # ----------------------------------------------------------------------
    # Internal API Key Management (for CLI)
    # ----------------------------------------------------------------------

    def get_internal_key(self) -> str:
        """
        Get the internal API key (raises if not found).

        Returns:
            Internal API key string

        Raises:
            RuntimeError: If internal key not found in database
        """
        key = self.db.get_meta("internal_key")
        if not key:
            raise RuntimeError("Internal API key not found in DB. Key should be generated during initialization.")
        return key

    def get_or_create_internal_key(self) -> str:
        """
        Get or create the internal API key for CLI-only endpoints.
        This key is used by the CLI to access internal processing endpoints.

        Returns:
            Internal API key string (existing or newly generated)
        """
        key = self.db.get_meta("internal_key")
        if key:
            return key
        new_key = secrets.token_urlsafe(32)
        self.db.set_meta("internal_key", new_key)
        logging.info("[KeyManagement] Generated new internal API key for CLI access.")
        return new_key

    def rotate_internal_key(self) -> str:
        """
        Generate a new internal API key, replacing any existing one.

        Returns:
            New internal API key string

        Warning:
            This invalidates the old key immediately. CLI will need to
            restart to pick up the new key.
        """
        new_key = secrets.token_urlsafe(32)
        self.db.set_meta("internal_key", new_key)
        logging.warning("[KeyManagement] Internal API key rotated - old key invalidated")
        return new_key

    # ----------------------------------------------------------------------
    # Admin Password Management
    # ----------------------------------------------------------------------

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using SHA-256 with salt.

        Args:
            password: Plaintext password

        Returns:
            Hashed password in format "salt:hash"
        """
        salt = secrets.token_hex(16)
        pwd_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return f"{salt}:{pwd_hash}"

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against a stored hash.

        Args:
            password: Plaintext password to verify
            password_hash: Stored hash in format "salt:hash"

        Returns:
            True if password matches, False otherwise
        """
        try:
            salt, pwd_hash = password_hash.split(":", 1)
            computed = hashlib.sha256((password + salt).encode()).hexdigest()
            return computed == pwd_hash
        except (ValueError, AttributeError):
            return False

    def get_admin_password_hash(self) -> str:
        """
        Get admin password hash from DB (raises if not found).

        Returns:
            Password hash string

        Raises:
            RuntimeError: If password not found in database
        """
        password_hash = self.db.get_meta("admin_password_hash")
        if not password_hash:
            raise RuntimeError("Admin password not found in DB. Password should be generated during initialization.")
        return password_hash

    def get_or_create_admin_password(self, config_password: str | None = None) -> str:
        """
        Get or create the admin password hash for web UI authentication.

        On first run:
        - If config_password is provided, hash and store it
        - If not provided, generate random password and log it

        On subsequent runs:
        - Return existing hash from DB (config_password is ignored)

        Args:
            config_password: Optional password from config file

        Returns:
            Plaintext password if auto-generated (for logging), empty string otherwise
        """
        existing_hash = self.db.get_meta("admin_password_hash")
        if existing_hash:
            # Password already set in DB - ignore config
            return ""

        # First run - initialize password
        if config_password:
            # Use config password
            password_hash = self.hash_password(config_password)
            self.db.set_meta("admin_password_hash", password_hash)
            logging.info("[KeyManagement] Admin password set from config file.")
            return ""  # Don't log config password
        else:
            # Generate random password
            random_password = secrets.token_urlsafe(16)
            password_hash = self.hash_password(random_password)
            self.db.set_meta("admin_password_hash", password_hash)
            logging.warning("[KeyManagement] ========================================")
            logging.warning("[KeyManagement] AUTO-GENERATED ADMIN PASSWORD:")
            logging.warning(f"[KeyManagement]   {random_password}")
            logging.warning("[KeyManagement] ========================================")
            logging.warning("[KeyManagement] Save this password - it won't be shown again!")
            return random_password

    def reset_admin_password(self, new_password: str) -> None:
        """
        Reset the admin password to a new value.

        Args:
            new_password: New plaintext password

        Warning:
            This invalidates all existing web UI sessions.
        """
        password_hash = self.hash_password(new_password)
        self.db.set_meta("admin_password_hash", password_hash)
        logging.warning("[KeyManagement] Admin password reset - all sessions invalidated")

    # ----------------------------------------------------------------------
    # Session Management (Web UI)
    # ----------------------------------------------------------------------

    def create_session(self) -> str:
        """
        Create a new session token with expiry.
        Write-through cache: stores in both memory (fast reads) and DB (persistence).

        Returns:
            Session token string
        """
        session_token = secrets.token_urlsafe(32)
        expiry = time.time() + SESSION_TIMEOUT_SECONDS

        # Write to memory cache (fast reads)
        _session_cache[session_token] = expiry

        # Write to DB (persistence across restarts)
        self.db.create_session(session_token, expiry)

        logging.info(f"[KeyManagement] Created new session (expires in {SESSION_TIMEOUT_SECONDS}s)")
        return session_token

    @staticmethod
    def validate_session(session_token: str) -> bool:
        """
        Validate a session token and check if it's expired.
        Uses in-memory cache for performance (no DB hit per request).

        Args:
            session_token: Session token to validate

        Returns:
            True if session is valid and not expired, False otherwise
        """
        # Check memory cache
        expiry = _session_cache.get(session_token)

        if expiry is None:
            return False

        # Check if expired
        if time.time() > expiry:
            # Expired - remove from cache
            _session_cache.pop(session_token, None)
            return False

        return True

    def invalidate_session(self, session_token: str) -> None:
        """
        Invalidate a session (logout).
        Removes from both memory cache and DB.

        Args:
            session_token: Session token to invalidate
        """
        # Remove from memory cache
        _session_cache.pop(session_token, None)

        # Remove from DB
        self.db.delete_session(session_token)

        logging.info("[KeyManagement] Session invalidated (logout)")

    def cleanup_expired_sessions(self) -> int:
        """
        Remove all expired sessions from both memory cache and DB.

        Returns:
            Number of sessions cleaned up
        """
        now = time.time()
        expired = [token for token, expiry in _session_cache.items() if expiry < now]

        # Remove from memory cache
        for token in expired:
            _session_cache.pop(token, None)

        # Cleanup DB (get actual count from DB operation)
        db_count = self.db.cleanup_expired_sessions()

        if expired or db_count:
            logging.info(f"[KeyManagement] Cleaned up {len(expired)} expired session(s) from cache, {db_count} from DB")

        return len(expired)

    def load_sessions_from_db(self) -> int:
        """
        Load all non-expired sessions from DB into memory cache on startup.

        Returns:
            Number of sessions loaded
        """
        sessions = self.db.load_all_sessions()
        _session_cache.update(sessions)
        logging.info(f"[KeyManagement] Loaded {len(sessions)} active session(s) from database")
        return len(sessions)


# Backward compatibility: expose session cache for tests
_sessions = _session_cache
