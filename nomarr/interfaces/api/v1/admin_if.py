"""Admin API router shell.

NOTE: Queue management endpoints have been removed with the discovery-based worker system.
Processing state is now managed via ``file_states`` / ``file_has_state`` graph edges.
This router is kept for future admin endpoint expansion.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["admin"], prefix="/v1/admin")
