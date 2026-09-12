"""Persistence wrappers for the file tag-writing workflow.

Absorbs the intent-level `db.library.*` / `db.app.*` calls used by
``write_file_tags_wf`` so the workflow never touches persistence directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import get_library_record
from nomarr.components.library.reconciliation_comp import release_claim
from nomarr.components.tagging.tag_query_comp import get_song_tags
from nomarr.components.tagging.tag_write_comp import set_song_tags, set_song_tags_batch

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.tags_dataclass import Tags
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File retrieval
# ---------------------------------------------------------------------------


def get_file_for_writing(
    db: Database,
    file_key: str,
) -> tuple[int, str, Song | None]:
    """Resolve a claimed file handle to its semantic ``Song`` via the facade.

    The claim handle is an integer-keyed string produced by the reconciliation
    queue. Persistence's narrow ``resolve_song_identity`` adapter maps the private
    handle to the mutable ``SongIdentity`` locator, and ``db.library.get_song``
    returns the semantic ``Song`` value — never a raw row, dict, or generated id
    projection. Returns ``(file_id, file_key, song)`` with ``song`` ``None`` when
    the handle no longer resolves.
    """
    file_id = int(file_key)
    identity = db.library.resolve_song_identity(file_id)
    if identity is None:
        return file_id, file_key, None
    return file_id, file_key, db.library.get_song(identity)


# ---------------------------------------------------------------------------
# Library root resolution
# ---------------------------------------------------------------------------


def resolve_library_root(
    db: Database,
    library: Library,
) -> Path | None:
    """Return the library's root path, or ``None`` if the library is missing."""
    library_doc = get_library_record(db, library, include_scan=False)
    if not library_doc:
        return None
    return Path(library_doc.root_path)


# ---------------------------------------------------------------------------
# Tag retrieval / mutation
# ---------------------------------------------------------------------------


def get_nomarr_tags(
    db: Database,
    file_id: int,
) -> Tags | None:
    """Fetch Nomarr-namespaced tags for *file_id*.

    Returns ``None`` when the file has no nomarr tags. Equivalent to calling the
    component-owned tag query helper with ``nomarr_only=True``.
    """
    return get_song_tags(db, file_id, nomarr_only=True)


# All three mood tier names that must always be written (or cleared) together.
# Writing an empty list for a name deletes any existing edges for it,
# which prevents stale tiers from persisting when the tier count drops.
_MOOD_TIER_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


def save_mood_tags(
    db: Database,
    song: SongIdentity,
    mood_tags: Tags | None,
) -> int:
    """Write mood-* tags to the database for a natural song locator."""
    written: dict[str, list] = {}
    if mood_tags is not None:
        for tag in mood_tags:
            nomarr_name = f"nom:{tag.name}" if not tag.name.startswith("nom:") else tag.name
            written[nomarr_name] = list(tag.values)

    count = 0
    for name in _MOOD_TIER_NAMES:
        values = written.get(name, [])
        set_song_tags(db, song, name, list(values))
        if values:
            count += 1
    return count


def save_mood_tags_batch(
    db: Database,
    items: list[tuple[SongIdentity, Tags | None]],
) -> int:
    """Write mood tags for multiple natural song locators."""
    if not items:
        return 0

    entries: list[dict] = []
    for song, mood_tags in items:
        written: dict[str, list] = {}
        if mood_tags is not None:
            for tag in mood_tags:
                nomarr_name = f"nom:{tag.name}" if not tag.name.startswith("nom:") else tag.name
                written[nomarr_name] = list(tag.values)
        entries.extend({"song": song, "name": name, "values": written.get(name, [])} for name in _MOOD_TIER_NAMES)

    set_song_tags_batch(db, entries)
    return sum(1 for entry in entries if entry["values"])


# ---------------------------------------------------------------------------
# Claim / state mutation
# ---------------------------------------------------------------------------


def release_file_claim(
    db: Database,
    file_key: str,
    worker_id: str,
) -> None:
    """Release a write claim without updating projection state.

    Swallows exceptions so callers in error paths don't need try/except.
    """
    try:
        song = db.library.resolve_song_identity(int(file_key))
        if song is not None:
            release_claim(db, song, worker_id)
    except (ValueError, RuntimeError) as exc:
        logger.warning(
            "[file_write_comp] Failed to release claim for %s: %s",
            file_key,
            exc,
            exc_info=True,
        )
