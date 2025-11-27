"""
Web package.

Exports the combined web router for all web UI endpoints.
Individual endpoint implementations live in *_if.py modules.
"""

from .router import router

__all__ = ["router"]
