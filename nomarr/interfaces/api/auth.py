"""
Authentication logic for the FastAPI application.
Thin wrapper around KeyManagementService for FastAPI dependency injection.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from nomarr.services.keys import KeyManagementService

auth_scheme = HTTPBearer(auto_error=False)


def get_key_service() -> KeyManagementService:
    """Get the KeyManagementService singleton instance."""
    from nomarr.app import application

    if "keys" not in application.services:
        raise RuntimeError("KeyManagementService not initialized")
    service = application.services["keys"]
    if not isinstance(service, KeyManagementService):
        raise RuntimeError("Invalid KeyManagementService instance")
    return service


async def verify_key(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """Verify API key using KeyManagementService."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = creds.credentials.strip()

    key_service = get_key_service()
    api_key = key_service.get_api_key()

    if api_key is None:
        raise HTTPException(status_code=500, detail="API key not initialized")
    if token != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def verify_session(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    """Verify session token using the singleton KeyManagementService instance."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = creds.credentials.strip()

    key_service = get_key_service()
    if not key_service.validate_session(token):
        raise HTTPException(status_code=403, detail="Invalid or expired session")


def hash_password(password: str) -> str:
    """
    Hash a password. Pure utility function - stateless.
    """
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService.hash_password(password)


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify a password against a hash. Pure utility function - stateless.
    """
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService.verify_password(password, password_hash)


def get_admin_password_hash() -> str:
    """
    Get admin password hash using the singleton KeyManagementService instance.

    Returns:
        Password hash string

    Raises:
        RuntimeError: If password not found or service not initialized
    """
    return get_key_service().get_admin_password_hash()


def create_session() -> str:
    """Create a new session using the singleton KeyManagementService instance."""
    return get_key_service().create_session()


def validate_session(session_token: str) -> bool:
    """
    Validate a session token using the singleton KeyManagementService instance.

    Note: Use the singleton service instance to maintain proper architecture.
    """
    return get_key_service().validate_session(session_token)


def invalidate_session(session_token: str) -> None:
    """Invalidate a session using the singleton KeyManagementService instance."""
    get_key_service().invalidate_session(session_token)


def cleanup_expired_sessions() -> int:
    """Cleanup expired sessions using the singleton KeyManagementService instance."""
    return get_key_service().cleanup_expired_sessions()


def load_sessions_from_db() -> int:
    """Load sessions from database using KeyManagementService."""
    return get_key_service().load_sessions_from_db()


# Export session cache for backward compatibility with tests
