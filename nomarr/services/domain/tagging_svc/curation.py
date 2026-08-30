"""Tag curation operations for TaggingService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.tagging.tag_query_comp import get_song_tags
from nomarr.components.tagging.tag_write_comp import relink_tag_edges, set_song_tags
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class TaggingCurationMixin:
    """Mixin providing tag curation methods."""

    db: Database

    def _mark_song_write_pending(self, song_id: int) -> None:
        """Queue a curated song for both projection and file write-back."""
        transition_song_state(self.db, [song_id], STATE_WRITTEN, STATE_NOT_WRITTEN)
        if STATE_TAGS_CURRENT in self.db.app.song_state_membership(song_id):
            transition_song_state(self.db, [song_id], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)

    @staticmethod
    def _reject_nom_prefix(name: str | None = None, *, identity: TagRef | None = None) -> None:
        """Raise ValueError if the tag or name has the read-only nom: prefix (ADR-009)."""
        if name is not None and name.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: name={name}"
            raise ValueError(msg)
        if identity is not None and identity.name.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: {identity.name}={identity.value}"
            raise ValueError(msg)

    def _get_tag_or_error(self, tag_id: str) -> TagRef:
        """Resolve an opaque external tag id to its domain identity, or raise ValueError."""
        identity = self.db.resolve_tag_identity(int(tag_id))
        if identity is None:
            msg = f"Tag not found: {tag_id}"
            raise ValueError(msg)
        return identity

    def rename_tag(self, tag_id: str, new_value: str) -> RenameResult:
        """Rename a tag to a new value.

        Rejects nom: prefix tags (ADR-009). Creates target tag if needed,
        then relinks all edges from source to target.

        Args:
            tag_id: Source tag id (e.g., "12345")
            new_value: New value for the tag

        Returns:
            RenameResult with moved count and whether it merged into existing

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(tag_id)
        self._reject_nom_prefix(identity=source_tag)

        target_identity = self.db.library.ensure_tag(TagRef(name=source_tag.name, value=new_value, namespace=""))
        merged_into_existing = target_identity != source_tag

        relink = relink_tag_edges(self.db, source_tag, target_identity)

        for song in self.db.library.find_songs_with_tag(target_identity, limit=None):
            self._mark_song_write_pending(song.song_id)

        return RenameResult(moved=relink.moved, merged_into_existing=merged_into_existing)

    def merge_tags(self, source_tag_ids: list[str], canonical_tag_id: str) -> MergeResult:
        """Merge multiple source tags into a canonical tag.

        Rejects nom: prefix tags (ADR-009). Iterates each source through
        relink_tag_edges to the canonical target.

        Args:
            source_tag_ids: Tag ids to merge FROM
            canonical_tag_id: Tag id to merge INTO

        Returns:
            MergeResult with total_moved and sources_removed counts

        Raises:
            ValueError: If any tag not found or has nom: prefix

        """
        canonical_tag = self._get_tag_or_error(canonical_tag_id)
        self._reject_nom_prefix(identity=canonical_tag)

        total_moved = 0
        sources_removed = 0

        for source_id in source_tag_ids:
            if source_id == canonical_tag_id:
                continue
            source_tag = self._get_tag_or_error(source_id)
            self._reject_nom_prefix(identity=source_tag)

            relink = relink_tag_edges(self.db, source_tag, canonical_tag)
            total_moved += relink.moved
            if relink.source_orphaned:
                sources_removed += 1

        for song in self.db.library.find_songs_with_tag(canonical_tag, limit=None):
            self._mark_song_write_pending(song.song_id)

        return MergeResult(total_moved=total_moved, sources_removed=sources_removed)

    def split_tag(self, source_tag_id: str, song_ids: list[str], new_value: str) -> SplitResult:
        """Split selected songs from a tag into a new tag value.

        Rejects nom: prefix tags (ADR-009). Creates a new tag with the given
        value and relinks only the specified songs.

        Args:
            source_tag_id: Tag id to split FROM
            song_ids: Song ids to move to the new tag
            new_value: Value for the new tag

        Returns:
            SplitResult with moved count and whether a new tag was created

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(source_tag_id)
        self._reject_nom_prefix(identity=source_tag)

        target_identity = self.db.library.ensure_tag(TagRef(name=source_tag.name, value=new_value, namespace=""))
        new_tag_created = target_identity != source_tag

        song_identity_map = self.db.library.resolve_song_identities([int(sid) for sid in song_ids])
        relink = relink_tag_edges(
            self.db,
            source_tag,
            target_identity,
            song_identities=list(song_identity_map.values()),
        )

        for song_id in song_ids:
            self._mark_song_write_pending(int(song_id))

        return SplitResult(moved=relink.moved, new_tag_created=new_tag_created)

    def update_song_tags(self, song_id: str, name: str, values: list[str]) -> dict:
        """Update the value of a single tag on a song.

        Args:
            song_id: The song identifier.
            name: The tag name to update.
            values: The new values to assign.

        Returns:
            A dict keyed by ``file_id`` (API contract), ``name`` and ``tags``.
        """
        self._reject_nom_prefix(name=name)
        set_song_tags(self.db, int(song_id), name, list(values))
        self._mark_song_write_pending(int(song_id))
        tags = get_song_tags(self.db, int(song_id), name=name)
        if tags is None:
            tags_list: list[dict[str, Any]] = []
        else:
            tags_list = [
                {
                    "key": tag.name,
                    "value": str(value),
                    "tag_type": "string",
                    "is_nomarr": tag.name.startswith("nom:"),
                }
                for tag in tags
                for value in tag.values
            ]
        return {
            "file_id": song_id,
            "name": name,
            "tags": tags_list,
        }
