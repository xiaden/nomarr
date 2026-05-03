"""DTOs for tag curation operations (rename, merge, split, commit)."""

from __future__ import annotations

from typing import TypedDict


class RelinkResult(TypedDict):
    moved: int
    skipped: int
    source_orphaned: bool


class TagValueItem(TypedDict):
    id: str
    name: str
    value: str
    song_count: int


class TagListResult(TypedDict):
    tags: list[TagValueItem]
    total: int


class RenameResult(TypedDict):
    moved: int
    merged_into_existing: bool


class MergeResult(TypedDict):
    total_moved: int
    sources_removed: int


class SplitResult(TypedDict):
    moved: int
    new_tag_created: bool


class CommitResult(TypedDict):
    started: bool
    pending_files: int


class TagSongItem(TypedDict):
    file_id: str
    title: str
    artist: str
    album: str
    path: str
