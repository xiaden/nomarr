"""Key Management Service.

Centralized service for managing authentication credentials:
- Public API keys (for Lidarr/external integrations)
- Admin passwords (for web UI authentication)
- Session tokens (for web UI session management)

Architecture Notes:
- This service uses dependency injection: Database must be provided at construction time.
- Interfaces must NOT construct this service directly with `KeyManagementService(db)`.
- Services are instantiated once during app wiring (see Application.start() in app.py).
- Session cache is module-level for performance but accessed only through instance methods.
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

import bcrypt

from nomarr.helpers.time_helper import now_s

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database
SESSION_TIMEOUT_SECONDS = 86400
_session_cache: dict[str, float] = {}


class KeyManagementService:
    """Service for managing API keys, passwords, and sessions.

    This service requires Database injection at construction time.
    Do NOT construct this service directly in interface layer code.
    Use the singleton instance from Application.services["keys"].
    """

    def __init__(self, db: Database) -> None:
        """Initialize the key management service with injected dependencies.

        Args:
            db: Database instance for persistence (injected by Application during startup)

        Note:
            This service should be instantiated once during app wiring, not per-request.

        """
        self._db = db

    def get_api_key(self) -> str | None:
        """Get the public API key (returns None if not found).

        Returns:
            API key string if it exists, None otherwise

        Note:
            Use this for validation. Use get_or_create_api_key() during initialization.

        """
        return self._db.meta.get("api_key")

    def get_or_create_api_key(self) -> str:
        """Get or create the public API key for external endpoints.
        This key is used by Lidarr and other external integrations.

        Returns:
            API key string (existing or newly generated)

        """
        key = self._db.meta.get("api_key")
        if key:
            return key
        new_key = secrets.token_urlsafe(32)
        self._db.meta.set("api_key", new_key)
        logger.info("[KeyManagement] Generated new API key on first run.")
        return new_key

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt (secure password hashing).

        Args:
            password: Plaintext password

        Returns:
            Bcrypt password hash

        """
        pwd_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt(rounds=12)
        pwd_hash = bcrypt.hashpw(pwd_bytes, salt)
        return str(pwd_hash.decode("utf-8"))

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against a stored bcrypt hash.

        Args:
            password: Plaintext password to verify
            password_hash: Stored bcrypt hash

        Returns:
            True if password matches, False otherwise

        """
        try:
            pwd_bytes = password.encode("utf-8")
            hash_bytes = password_hash.encode("utf-8")
            return bool(bcrypt.checkpw(pwd_bytes, hash_bytes))
        except (ValueError, AttributeError, ImportError):
            return False

    def get_admin_password_hash(self) -> str:
        """Get admin password hash from DB (raises if not found).

        Returns:
            Password hash string

        Raises:
            RuntimeError: If password not found in database

        """
        password_hash = self._db.meta.get("admin_password_hash")
        if not password_hash:
            msg = "Admin password not found in DB. Password should be generated during initialization."
            raise RuntimeError(msg)
        return password_hash

    def get_or_create_admin_password(self, config_password: str | None = None) -> str:
        """Get or create the admin password hash for web UI authentication.

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
        existing_hash = self._db.meta.get("admin_password_hash")
        if existing_hash:
            return ""
        if config_password:
            password_hash = self.hash_password(config_password)
            self._db.meta.set("admin_password_hash", password_hash)
            logger.info("[KeyManagement] Admin password set from config file.")
            return ""
        random_password = secrets.token_urlsafe(16)
        password_hash = self.hash_password(random_password)
        self._db.meta.set("admin_password_hash", password_hash)
        logger.warning("[KeyManagement] ========================================")
        logger.warning("[KeyManagement] AUTO-GENERATED ADMIN PASSWORD:")
        logger.warning(f"[KeyManagement]   {random_password}")
        logger.warning("[KeyManagement] ========================================")
        logger.warning("[KeyManagement] Save this password - it won't be shown again!")
        return random_password

    def reset_admin_password(self, new_password: str) -> None:
        """Reset the admin password to a new value.

        Args:
            new_password: New plaintext password

        Warning:
            This invalidates all existing web UI sessions.

        """
        password_hash = self.hash_password(new_password)
        self._db.meta.set("admin_password_hash", password_hash)
        logger.warning("[KeyManagement] Admin password reset - all sessions invalidated")

    def create_session(self) -> str:
        """Create a new session token with expiry.
        Write-through cache: stores in both memory (fast reads) and DB (persistence).

        Returns:
            Session token string

        """
        session_token = secrets.token_urlsafe(32)
        expiry = now_s().value + SESSION_TIMEOUT_SECONDS
        _session_cache[session_token] = expiry
        self._db.sessions.create_session(session_id=session_token, user_id="admin", expiry_timestamp=int(expiry * 1000))
        logger.info(f"[KeyManagement] Created new session (expires in {SESSION_TIMEOUT_SECONDS}s)")
        return session_token

    def validate_session(self, session_token: str) -> bool:
        """Validate a session token and check if it's expired.
        Uses in-memory cache for performance (no DB hit per request).

        Args:
            session_token: Session token to validate

        Returns:
            True if session is valid and not expired, False otherwise

        Note:
            This method accesses the module-level session cache but should only be called
            through service instances to maintain proper architecture boundaries.

        """
        expiry = _session_cache.get(session_token)
        if expiry is None:
            return False
        if now_s().value > expiry:
            _session_cache.pop(session_token, None)
            return False
        return True

    def invalidate_session(self, session_token: str) -> None:
        """Invalidate a session (logout).
        Removes from both memory cache and DB.

        Args:
            session_token: Session token to invalidate

        """
        _session_cache.pop(session_token, None)
        self._db.sessions.delete(session_token)
        logger.info("[KeyManagement] Session invalidated (logout)")

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions from both memory cache and DB.

        Returns:
            Number of sessions cleaned up from cache

        """
        now = now_s().value
        expired = [token for token, expiry in _session_cache.items() if expiry < now]
        for token in expired:
            _session_cache.pop(token, None)
        db_count = self._db.sessions.cleanup_expired()
        if expired or db_count:
            logger.info(f"[KeyManagement] Cleaned up {len(expired)} expired session(s) from cache, {db_count} from DB")
        return len(expired)

    def load_sessions_from_db(self) -> int:
        """Load all non-expired sessions from DB into memory cache on startup.

        Returns:
            Number of sessions loaded

        """
        sessions = self._db.sessions.load_all()
        _session_cache.update((s["session_id"], s["expiry_timestamp"] / 1000.0) for s in sessions)
        logger.info(f"[KeyManagement] Loaded {len(sessions)} active session(s) from database")
        return len(sessions)


_sessions = _session_cache
