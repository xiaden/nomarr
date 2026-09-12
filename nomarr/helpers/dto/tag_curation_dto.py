"""DTOs for tag curation operations (rename, merge, split, commit)."""

from __future__ import annotations

from typing import TypedDict


class RelinkResult(TypedDict):
    moved: int
    skipped: int
    source_orphaned: bool


class TagValueItem(TypedDict):
    """Service-facing projection for one listed tag value.

    ``namespace`` carries the complete natural identity so the HTTP interface
    encoder can emit a namespace-distinct opaque handle; it is an internal
    service/DTO field, not a public response field (the web response model
    exposes only ``id``/``name``/``value``/``song_count``).
    """

    id: str
    name: str
    value: str
    namespace: str
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
    """One tag-linked song row in the curation browse projection.

    ``file_id`` is an opaque ``nom1`` SongLocator token, not a generated
    integer. It is not stable across a root move and must never be parsed,
    compared to an integer, or used as a foreign key.
    """

    file_id: str
    title: str
    artist: str
    album: str
    path: str
