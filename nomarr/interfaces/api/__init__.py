"""
API layer package for Nomarr.
Exports FastAPI app, auth components, and models.
"""

from nomarr.interfaces.api.api_app import api_app
from nomarr.interfaces.api.auth import auth_scheme, verify_key
from nomarr.interfaces.api.models import (
    FlushRequest,
    InternalBatchRequest,
    InternalProcessRequest,
    RemoveJobRequest,
)

__all__ = [
    "FlushRequest",
    "InternalBatchRequest",
    "InternalProcessRequest",
    "RemoveJobRequest",
    "api_app",
    "auth_scheme",
    "verify_key",
]
