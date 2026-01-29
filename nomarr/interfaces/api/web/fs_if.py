"""Filesystem browser API endpoints.

Provides safe, read-only browsing of the music library directory.
All paths are resolved and validated to prevent directory traversal attacks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from nomarr.helpers.files_helper import resolve_library_path
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_config

router = APIRouter(prefix="/fs", tags=["filesystem"])


@router.get("/list")
async def list_directory(
    path: Annotated[str, Query(description="Relative path from library root")] = "",
    config: dict = Depends(get_config),
    _session: dict = Depends(verify_session),
) -> dict[str, Any]:
    """List contents of a directory within the music library.

    Security features:
    - All paths are resolved and validated against library_root root
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
    # Check if library_root is configured
    library_root = config.get("library_root")
    if not library_root:
        raise HTTPException(
            status_code=503,
            detail="Library path not configured. Set library_root in config.yaml",
        )

    try:
        # Securely resolve and validate the requested directory path
        # This handles all security checks: path traversal, symlinks, boundary validation
        requested_path = resolve_library_path(
            library_root=library_root,
            user_path=path,
            must_exist=True,
            must_be_file=False,  # Must be a directory
        )

        # Get library root for computing relative paths in response
        library_root = Path(library_root).resolve()

        # List directory contents
        entries: list[dict[str, str | bool]] = []
        for item in requested_path.iterdir():
            try:
                entries.append(
                    {
                        "name": item.name,
                        "is_dir": item.is_dir(),
                    },
                )
            except (OSError, PermissionError) as e:
                # Skip items we can't access
                logging.debug(f"[FS Browser] Skipping inaccessible item {item}: {e}")
                continue

        # Sort entries: directories first, then files, both alphabetically
        entries.sort(key=lambda x: (not x["is_dir"], str(x["name"]).lower()))

        # Compute relative path for response (empty string for root)
        relative_path = str(requested_path.relative_to(library_root))
        if relative_path == ".":
            relative_path = ""

        return {
            "path": relative_path,
            "entries": entries,
        }

    except ValueError as e:
        # Security helper raises ValueError with generic messages
        # Map these to appropriate HTTP error codes
        error_message = str(e)
        if "not configured" in error_message:
            status_code = 503
        elif "not found" in error_message.lower():
            status_code = 404
        elif "not a directory" in error_message.lower():
            status_code = 400
            error_message = "Path is not a directory"
        else:
            # Generic security error (traversal attempt, etc.)
            status_code = 400
            error_message = "Invalid path: directory traversal not allowed"

        logging.warning(f"[FS Browser] Path validation failed for {path!r}: {e}")
        raise HTTPException(status_code=status_code, detail=error_message) from e

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logging.exception(f"[FS Browser] Error listing directory: {e}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Internal error while listing directory"),
        ) from e
