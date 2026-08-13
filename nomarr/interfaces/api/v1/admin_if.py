"""Admin API router shell.

NOTE: Queue management endpoints have been removed with the discovery-based worker system.
Processing state is now managed via song-state assignments.
This router is kept for future admin endpoint expansion.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["admin"], prefix="/v1/admin")
