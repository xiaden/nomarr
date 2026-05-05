"""Helpers for parsing ONNX VRAM OOMs and updating stored model limits."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_META_PREFIX = "ml_model_vram:"
_OOM_PATTERN = re.compile(r"requested bytes of (\d+)")


def _fmt_bytes(n: int) -> str:
    """Format a byte count as a human-readable string (B / MB / GB)."""
    if n >= 1_073_741_824:
        return f"{n / 1_073_741_824:.2f} GB"
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    return f"{n} B"


def parse_oom_requested_bytes(error: BaseException) -> int | None:
    """Parse the requested-bytes value from a BFC arena OOM error message."""
    match = _OOM_PATTERN.search(str(error))
    if match is None:
        return None
    return int(match.group(1))


def update_model_vram_from_oom(db: Database, model_path: str, requested_bytes: int) -> int:
    """Write a corrected VRAM limit after a BFC arena OOM."""
    raw_doc = cast("dict[str, Any] | None", db.meta.get(key=f"{_META_PREFIX}{model_path}"))
    raw = None if raw_doc is None else raw_doc.get("value")
    base = int(raw) if raw is not None else requested_bytes
    new_limit = int(base * 1.25)
    db.meta.upsert(key=f"{_META_PREFIX}{model_path}", fields={"value": str(new_limit)})
    logger.warning(
        "[vram_probe] OOM self-heal: updated %s from %s to %s (%d bytes) — bumped probe by 25%%",
        model_path,
        _fmt_bytes(base),
        _fmt_bytes(new_limit),
        new_limit,
    )
    return new_limit
