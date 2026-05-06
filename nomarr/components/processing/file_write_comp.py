"""Persistence wrappers for the file tag-writing workflow.

Absorbs all db.library_files / db.libraries / db.tags calls from
``write_file_tags_wf`` so the workflow never touches persistence directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import get_file_by_id
from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.reconciliation_comp import release_claim
from nomarr.components.tagging.tag_query_comp import get_song_tags
from nomarr.components.tagging.tag_write_comp import set_song_tags, set_song_tags_batch

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

from nomarr.helpers.dto.tags_dto import Tags

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

    file_doc = get_file_by_id(db, file_id)
    return file_id, file_key, file_doc


# ---------------------------------------------------------------------------
# Library root resolution
# ---------------------------------------------------------------------------


def resolve_library_root(
    db: Database,
    library_id: str,
) -> Path | None:
    """Return the library's root path, or ``None`` if the library is missing."""
    library_doc = get_library_record(db, library_id, include_scan=False)
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

    Equivalent to calling the component-owned tag query helper with
    ``nomarr_only=True``.
    """
    return get_song_tags(db, file_id, nomarr_only=True)


# All three mood tier names that must always be written (or cleared) together.
# Writing an empty list for a name deletes any existing edges for it,
# which prevents stale tiers from persisting when the tier count drops.
_MOOD_TIER_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


def save_mood_tags(
    db: Database,
    file_id: str,
    mood_tags: Tags,
) -> int:
    """Write mood-* tags to the database for a file.

    Always writes all three mood tier keys (mood-strict, mood-regular,
    mood-loose). Tiers absent from *mood_tags* are explicitly cleared with an
    empty value list so that previously-written tiers do not persist when the
    tier count drops after recalibration.

    Args:
        db: Database instance
        file_id: File document ID (e.g. 'library_files/abc123')
        mood_tags: Tags DTO containing mood tags to write

    Returns:
        Number of tiers written with non-empty values

    """
    # Build lookup: normalised name -> values
    written: dict[str, list] = {}
    for tag in mood_tags:
        nomarr_name = f"nom:{tag.key}" if not tag.key.startswith("nom:") else tag.key
        written[nomarr_name] = tag.value

    count = 0
    for name in _MOOD_TIER_NAMES:
        values = written.get(name, [])
        set_song_tags(db, file_id, name, list(values))
        if values:
            count += 1
    return count


def save_mood_tags_batch(
    db: Database,
    items: list[tuple[str, Tags]],
) -> int:
    """Write mood tags for multiple files via constructor-backed verbs.

    Delegates to ``set_song_tags_batch`` which performs component-layer
    coordination: edge discovery per ``(song_id, name)`` pair, targeted edge
    deletion, tag upsert per unique ``(name, value)`` pair, and bulk edge
    insert.  Query count scales with the number of files and distinct tag
    values.

    Args:
        db: Database instance
        items: List of (file_id, mood_tags) tuples

    Returns:
        Number of (file_id, name) pairs written

    """
    if not items:
        return 0

    entries: list[dict] = []
    for file_id, mood_tags in items:
        # Build a lookup for this file's non-empty tiers
        written: dict[str, list] = {}
        for tag in mood_tags:
            nomarr_name = f"nom:{tag.key}" if not tag.key.startswith("nom:") else tag.key
            written[nomarr_name] = tag.value
        # Always emit all three tiers; absent ones get an empty list (→ delete)
        entries.extend({"song_id": file_id, "name": name, "values": written.get(name, [])} for name in _MOOD_TIER_NAMES)

    set_song_tags_batch(db, entries)
    return sum(1 for e in entries if e["values"])


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
        release_claim(db, file_key)
    except Exception as exc:
        logger.debug(
            "[file_write_comp] Failed to release claim for %s: %s",
            file_key,
            exc,
        )
