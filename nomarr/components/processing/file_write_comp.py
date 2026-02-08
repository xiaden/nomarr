"""Persistence wrappers for the file tag-writing workflow.

Absorbs all db.library_files / db.libraries / db.tags calls from
``write_file_tags_wf`` so the workflow never touches persistence directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

from nomarr.helpers.tags_dto import Tags

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File retrieval
# ---------------------------------------------------------------------------


def get_file_for_writing(
    db: Database,
    file_key: str,
) -> tuple[str, str, dict[str, Any] | None]:
    """Normalise *file_key* and fetch the library-file document.

    Returns:
        (file_id, file_key, file_doc) — *file_doc* is ``None`` when the
        document does not exist.
    """
    if file_key.startswith("library_files/"):
        file_id = file_key
        file_key = file_key.split("/")[1]
    else:
        file_id = f"library_files/{file_key}"

    file_doc = db.library_files.get_file_by_id(file_id)
    return file_id, file_key, file_doc


# ---------------------------------------------------------------------------
# Library root resolution
# ---------------------------------------------------------------------------


def resolve_library_root(
    db: Database,
    library_id: str,
) -> Path | None:
    """Return the library's root path, or ``None`` if the library is missing."""
    library_doc = db.libraries.get_library(library_id)
    if not library_doc:
        return None
    return Path(library_doc["root_path"])


# ---------------------------------------------------------------------------
# Tag retrieval / mutation
# ---------------------------------------------------------------------------


def get_nomarr_tags(
    db: Database,
    file_id: str,
) -> Tags:
    """Fetch Nomarr-namespaced tags for *file_id*.

    Equivalent to ``db.tags.get_song_tags(file_id, nomarr_only=True)``.
    """
    return db.tags.get_song_tags(file_id, nomarr_only=True)


def save_mood_tags(
    db: Database,
    file_id: str,
    mood_tags: Tags,
) -> int:
    """Write mood-* tags to the database for a file.

    Each tag in *mood_tags* is namespaced with 'nom:' prefix if not
    already present, then stored via ``set_song_tags``.

    Args:
        db: Database instance
        file_id: File document ID (e.g. 'library_files/abc123')
        mood_tags: Tags DTO containing mood tags to write

    Returns:
        Number of tags written

    """
    count = 0
    for tag in mood_tags:
        nomarr_rel = f"nom:{tag.key}" if not tag.key.startswith("nom:") else tag.key
        db.tags.set_song_tags(file_id, nomarr_rel, tag.value)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Claim / state mutation
# ---------------------------------------------------------------------------


def release_file_claim(
    db: Database,
    file_key: str,
) -> None:
    """Release a write claim without updating projection state.

    Swallows exceptions so callers in error paths don't need try/except.
    """
    try:
        db.library_files.release_claim(file_key)
    except Exception as exc:
        logger.debug(
            "[file_write_comp] Failed to release claim for %s: %s",
            file_key,
            exc,
        )


def mark_file_written(
    db: Database,
    file_key: str,
    *,
    mode: str,
    calibration_hash: str | None,
) -> None:
    """Record that tags were successfully written to *file_key*."""
    db.library_files.set_file_written(
        file_key,
        mode=mode,
        calibration_hash=calibration_hash,
    )
