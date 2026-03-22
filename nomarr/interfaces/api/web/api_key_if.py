"""API key management endpoints.

Exposes the Nomarr API key used by external integrations (Navidrome plugin, etc.).
Auth: session token (verify_session).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from nomarr.interfaces.api.auth import get_key_service, verify_session
from nomarr.interfaces.api.types.api_key_types import ApiKeyResponse
from nomarr.services.infrastructure.keys_svc import KeyManagementService

router = APIRouter(prefix="/api-key", tags=["API Key"], dependencies=[Depends(verify_session)])


@router.get("", response_model=ApiKeyResponse)
async def get_api_key(
    key_service: Annotated[KeyManagementService, Depends(get_key_service)],
) -> ApiKeyResponse:
    """Return the current API key."""
    key = key_service.get_or_create_api_key()
    return ApiKeyResponse(api_key=key)


@router.post("/regenerate", response_model=ApiKeyResponse)
async def regenerate_api_key(
    key_service: Annotated[KeyManagementService, Depends(get_key_service)],
) -> ApiKeyResponse:
    """Regenerate the API key and return the new value."""
    key = key_service.regenerate_api_key()
    return ApiKeyResponse(api_key=key)
