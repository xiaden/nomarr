"""Tag viewing endpoints for web UI."""

import logging
from typing import Any

import mutagen
from fastapi import APIRouter, Depends, HTTPException

from nomarr.helpers.files import validate_library_path
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_config

router = APIRouter(prefix="/api", tags=["Tags"])


# ──────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────


def _extract_mp3_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """Extract tags from MP3 (ID3v2) format."""
    tags = {}
    if hasattr(audio, "tags") and audio.tags:
        for key in audio.tags:
            if key.startswith("TXXX:"):
                tag_name = key[5:]
                if tag_name.startswith(f"{namespace}:"):
                    clean_name = tag_name[len(namespace) + 1 :]
                    values = audio.tags[key].text
                    tags[clean_name] = values if len(values) > 1 else values[0]
    return tags


def _extract_mp4_tags(audio: Any, namespace: str) -> dict[str, Any]:
    """Extract tags from MP4/M4A format."""
    tags = {}
    if hasattr(audio, "tags") and hasattr(audio.tags, "get"):
        for key, value in audio.tags.items():
            if key.startswith("----:com.apple.iTunes:"):
                tag_name = key[22:]
                if tag_name.startswith(f"{namespace}:"):
                    clean_name = tag_name[len(namespace) + 1 :]
                    tags[clean_name] = value[0].decode("utf-8") if isinstance(value[0], bytes) else str(value[0])
    return tags


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/show-tags", dependencies=[Depends(verify_session)])
async def web_show_tags(
    path: str,
    cfg: dict = Depends(get_config),
) -> dict[str, Any]:
    """Read tags from an audio file (web UI proxy)."""
    namespace = cfg.get("namespace", "essentia")
    library_root = cfg.get("library_root", "")

    # Validate path to prevent directory traversal (includes existence check)
    validated_path = validate_library_path(path, library_root)

    try:
        audio = mutagen.File(validated_path)
        if audio is None:
            raise HTTPException(status_code=400, detail="Unsupported audio format")

        # Try MP3 format first, then MP4
        tags = _extract_mp3_tags(audio, namespace)
        if not tags:
            tags = _extract_mp4_tags(audio, namespace)

        return {
            "path": validated_path,
            "namespace": namespace,
            "tags": tags,
            "count": len(tags),
        }

    except Exception as e:
        logging.exception(f"[Web API] Error reading tags from {validated_path}")
        raise HTTPException(status_code=500, detail=f"Error reading tags: {e}") from e
