"""Tag write and curation helpers extracted from legacy tag persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from nomarr.components.tagging.tag_query_comp import _narrow_tag_list
from nomarr.helpers.dto.tag_curation_dto import RelinkResult
from nomarr.helpers.dto.tags_dto import TagValue

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


async def find_or_create_tag(db: Database, name: str, value: TagValue) -> int:
    """Find or create one tag vertex and return its id."""
    return await db.library.find_or_create_tag(name, str(value), "")


def _tag_name(tag_doc: Mapping[str, Any]) -> str | None:
    tag_name = tag_doc.get("name", tag_doc.get("key"))
    return str(tag_name) if isinstance(tag_name, str) else None


def _tag_id(tag_doc: Mapping[str, Any]) -> int | None:
    tag_id = tag_doc.get("id")
    return int(tag_id) if isinstance(tag_id, int) else None


def _merge_replaced_tags(
    existing_tags: Sequence[Mapping[str, Any]],
    *,
    replacements_by_name: dict[str, list[TagValue]],
) -> list[dict[str, Any]]:
    replaced_names = set(replacements_by_name)
    merged_tags = [dict(tag_doc) for tag_doc in existing_tags if _tag_name(tag_doc) not in replaced_names]
    for name, values in replacements_by_name.items():
        merged_tags.extend({"name": name, "value": value} for value in dict.fromkeys(values))
    return merged_tags


async def set_song_tags(db: Database, song_id: int, name: str, values: list[TagValue]) -> None:
    """Replace all tags for one ``song_id`` + ``name`` pair."""
    existing_tags = (await db.library.list_file_tags_for_files([song_id])).get(song_id, [])
    await db.library.replace_file_tags(
        song_id,
        _merge_replaced_tags(existing_tags, replacements_by_name={name: values}),
    )


def _validate_tag_value(value: object) -> TagValue:
    """Runtime validation that a value is an acceptable tag value type."""
    if isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"Invalid tag value type: {type(value).__name__}")


async def set_song_tags_batch(db: Database, entries: list[dict[str, Any]]) -> None:
    """Replace tags for many ``(song_id, name)`` pairs using intent-level file-tag writes."""
    if not entries:
        return

    replacements_by_song: dict[int, dict[str, list[TagValue]]] = {}
    for entry in entries:
        song_id = int(entry["song_id"])
        name = str(entry["name"])
        values = [_validate_tag_value(value) for value in entry["values"]]
        song_replacements = replacements_by_song.setdefault(song_id, {})
        song_replacements.setdefault(name, []).extend(values)

    existing_tags_by_song = await db.library.list_file_tags_for_files(list(replacements_by_song))
    for song_id, replacements_by_name in replacements_by_song.items():
        await db.library.replace_file_tags(
            song_id,
            _merge_replaced_tags(
                existing_tags_by_song.get(song_id, []),
                replacements_by_name=replacements_by_name,
            ),
        )


async def add_song_tag(db: Database, song_id: int, name: str, value: TagValue) -> None:
    """Add one tag value to a song without replacing other values for the name."""
    existing_tags = (await db.library.list_file_tags_for_files([song_id])).get(song_id, [])
    await db.library.replace_file_tags(
        song_id,
        [*(dict(t) for t in existing_tags), {"name": name, "value": value}],
    )


async def delete_song_tags(db: Database, song_id: int) -> None:
    """Delete all tag edges for one song."""
    await db.library.remove_file_tags(song_id)


async def relink_tag_edges(
    db: Database,
    source_tag_id: int,
    target_tag_id: int,
    song_ids: list[int] | None = None,
) -> RelinkResult:
    """Move song tag references from one tag vertex to another via library intents."""
    if source_tag_id == target_tag_id:
        return {"moved": 0, "skipped": 0, "source_orphaned": False}

    all_file_docs = _narrow_tag_list(await db.library.list_files(limit=None))
    all_file_ids = [file_id for file_doc in all_file_docs if isinstance((file_id := file_doc.get("id")), int)]
    if not all_file_ids:
        return {"moved": 0, "skipped": 0, "source_orphaned": False}

    all_tags_by_file = await db.library.list_file_tags_for_files(all_file_ids)
    allowed_song_ids = set(song_ids) if song_ids is not None else None
    selected_source_file_ids: list[int] = []
    moved = 0
    skipped = 0
    source_outside_selection = False

    for file_id in all_file_ids:
        tag_docs = all_tags_by_file.get(file_id, [])
        has_source = any(_tag_id(tag_doc) == source_tag_id for tag_doc in tag_docs)
        if not has_source:
            continue
        if allowed_song_ids is not None and file_id not in allowed_song_ids:
            source_outside_selection = True
            continue

        selected_source_file_ids.append(file_id)
        has_target = any(_tag_id(tag_doc) == target_tag_id for tag_doc in tag_docs)
        if has_target:
            skipped += 1
        else:
            moved += 1

    if not selected_source_file_ids:
        return {"moved": 0, "skipped": 0, "source_orphaned": False}

    if song_ids is None:
        await db.library.replace_tag_references(source_tag_id, target_tag_id)
    else:
        await db.library.replace_selected_tag_references(selected_source_file_ids, source_tag_id, target_tag_id)

    return {
        "moved": moved,
        "skipped": skipped,
        "source_orphaned": not source_outside_selection,
    }
