"""
Filesystem browser API endpoints.

Provides safe, read-only browsing of the music library directory.
All paths are resolved and validated to prevent directory traversal attacks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from nomarr.app import application
from nomarr.interfaces.api.auth import verify_session

router = APIRouter(prefix="/web/api/fs", tags=["filesystem"])


@router.get("/list")
async def list_directory(
    path: str = Query("", description="Relative path from library root"),
    _session: dict = Depends(verify_session),
) -> dict[str, Any]:
    """
    List contents of a directory within the music library.

    Security features:
    - All paths are resolved and validated against library_path root
    - Directory traversal attempts (.., symlinks) are rejected
    - Only returns relative paths, never absolute container paths
    - Read-only: no write/delete/move operations

    Args:
        path: Relative path from library root (empty string = root)

    Returns:
        {
            "path": "relative/path",
            "entries": [
                {"name": "Artist", "is_dir": true},
                {"name": "track.flac", "is_dir": false},
                ...
            ]
        }

    Raises:
        503: Library path not configured
        400: Invalid path or directory traversal attempt
        404: Path does not exist
    """
    # Check if library_path is configured
    if not application.library_path:
        raise HTTPException(
            status_code=503,
            detail="Library path not configured. Set library_path in config.yaml",
        )

    try:
        # Get library root and resolve it to canonical absolute path
        library_root = Path(application.library_path).resolve()

        # Construct requested path (join library_root with relative path)
        # This handles empty string correctly (returns library_root)
        requested_path = (library_root / path).resolve()

        # Security check: ensure resolved path is under library_root
        # This prevents directory traversal attacks (../, symlinks, etc.)
        try:
            requested_path.relative_to(library_root)
        except ValueError as e:
            logging.warning(
                f"[FS Browser] Directory traversal attempt blocked: "
                f"path={path!r} resolved to {requested_path} (outside {library_root})"
            )
            raise HTTPException(
                status_code=400,
                detail="Invalid path: directory traversal not allowed",
            ) from e

        # Check if path exists
        if not requested_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Path not found: {path}",
            )

        # Check if path is a directory
        if not requested_path.is_dir():
            raise HTTPException(
                status_code=400,
                detail="Path is not a directory",
            )

        # List directory contents
        entries = []
        for item in requested_path.iterdir():
            try:
                entries.append(
                    {
                        "name": item.name,
                        "is_dir": item.is_dir(),
                    }
                )
            except (OSError, PermissionError) as e:
                # Skip items we can't access
                logging.debug(f"[FS Browser] Skipping inaccessible item {item}: {e}")
                continue

        # Sort entries: directories first, then files, both alphabetically
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        # Compute relative path for response (empty string for root)
        relative_path = str(requested_path.relative_to(library_root))
        if relative_path == ".":
            relative_path = ""

        return {
            "path": relative_path,
            "entries": entries,
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logging.exception(f"[FS Browser] Error listing directory: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error while listing directory: {e!s}",
        ) from e
