"""Authentication endpoints for web UI."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from nomarr.interfaces.api.auth import (
    create_session,
    get_admin_password_hash,
    invalidate_session,
    verify_password,
    verify_session,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


# Request/Response models
class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    session_token: str
    expires_in: int  # seconds


class LogoutResponse(BaseModel):
    status: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Authenticate with admin password and receive a session token.
    The session token should be used for all subsequent /web/api/* requests.
    """
    try:
        password_hash = get_admin_password_hash()
    except RuntimeError as e:
        logging.error(f"[Web UI] Admin password not initialized: {e}")
        raise HTTPException(status_code=500, detail="Admin authentication not configured") from None

    if not verify_password(request.password, password_hash):
        logging.warning("[Web UI] Failed login attempt")
        raise HTTPException(status_code=403, detail="Invalid password")

    session_token = create_session()
    logging.info("[Web UI] New session created")

    return LoginResponse(
        session_token=session_token,
        expires_in=86400,  # 24 hours
    )


@router.post("/logout", response_model=LogoutResponse, dependencies=[Depends(verify_session)])
async def logout(creds=Depends(verify_session)):
    """
    Invalidate the current session token (logout).
    """
    # Extract token from auth header
    bearer = HTTPBearer(auto_error=False)
    auth = await bearer(creds)
    if auth:
        invalidate_session(auth.credentials)

    return LogoutResponse(status="logged_out")
