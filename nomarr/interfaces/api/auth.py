"""
Authentication logic for the FastAPI application.
Thin wrapper around KeyManagementService for FastAPI dependency injection.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import nomarr.app as app

auth_scheme = HTTPBearer(auto_error=False)


def get_key_service():
    if "keys" not in app.application.services:
        raise RuntimeError("KeyManagementService not initialized")
    return app.application.services["keys"]


async def verify_key(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = creds.credentials.strip()
    if app.application.api_key is None:
        raise HTTPException(status_code=500, detail="API key not initialized")
    if token != app.application.api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


async def verify_session(creds: HTTPAuthorizationCredentials = Depends(auth_scheme)):
    if creds is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = creds.credentials.strip()
    from nomarr.services.keys import KeyManagementService

    if not KeyManagementService.validate_session(token):
        raise HTTPException(status_code=403, detail="Invalid or expired session")


def hash_password(password: str) -> str:
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService.hash_password(password)


def verify_password(password: str, password_hash: str) -> bool:
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService.verify_password(password, password_hash)


def get_or_create_api_key(db):
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService(db).get_or_create_api_key()


def get_or_create_admin_password(db, config_password=None):
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService(db).get_or_create_admin_password(config_password)


def get_api_key(db):
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService(db).get_api_key()


def get_admin_password_hash(db):
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService(db).get_admin_password_hash()


def create_session():
    if "keys" not in app.application.services:
        raise RuntimeError("KeyManagementService not initialized")
    return app.application.services["keys"].create_session()


def validate_session(session_token: str) -> bool:
    from nomarr.services.keys import KeyManagementService

    return KeyManagementService.validate_session(session_token)


def invalidate_session(session_token: str):
    if "keys" not in app.application.services:
        raise RuntimeError("KeyManagementService not initialized")
    app.application.services["keys"].invalidate_session(session_token)


def cleanup_expired_sessions() -> int:
    if "keys" not in app.application.services:
        raise RuntimeError("KeyManagementService not initialized")
    return app.application.services["keys"].cleanup_expired_sessions()


def load_sessions_from_db() -> int:
    if "keys" not in app.application.services:
        raise RuntimeError("KeyManagementService not initialized")
    return app.application.services["keys"].load_sessions_from_db()


# Export session cache for backward compatibility with tests
