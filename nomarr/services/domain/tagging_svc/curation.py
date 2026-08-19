"""Tag curation operations for TaggingService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.tagging.tag_query_comp import get_song_tags, get_tag, list_songs_for_tag
from nomarr.components.tagging.tag_write_comp import find_or_create_tag, relink_tag_edges, set_song_tags
from nomarr.helpers.constants.file_states import STATE_NOT_WRITTEN, STATE_WRITTEN
from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class TaggingCurationMixin:
    """Mixin providing tag curation methods."""

    db: Database

    @staticmethod
    def _reject_nom_prefix(name: str | None = None, *, tag_doc: dict[str, Any] | None = None) -> None:
        """Raise ValueError if the tag or name has the read-only nom: prefix (ADR-009)."""
        if name is not None and name.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: name={name}"
            raise ValueError(msg)
        if tag_doc is not None and str(tag_doc.get("name", "")).startswith("nom:"):
            msg = (
                "Tags with 'nom:' prefix are read-only and cannot be edited: "
                f"{tag_doc.get('name')}={tag_doc.get('value')}"
            )
            raise ValueError(msg)

    def _get_tag_or_error(self, tag_id: str) -> dict[str, Any]:
        """Fetch a tag document or raise ValueError."""
        tag = get_tag(self.db, int(tag_id))
        if not tag:
            msg = f"Tag not found: {tag_id}"
            raise ValueError(msg)
        return tag

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
        self._reject_nom_prefix(tag_doc=source_tag)

        target_tag_id = find_or_create_tag(self.db, source_tag["name"], new_value)
        merged_into_existing = target_tag_id != int(tag_id)

        relink = relink_tag_edges(self.db, int(tag_id), target_tag_id)

        song_ids = list_songs_for_tag(self.db, target_tag_id)
        for song_id in song_ids:
            transition_song_state(self.db, [int(song_id)], STATE_WRITTEN, STATE_NOT_WRITTEN)

        return RenameResult(moved=relink["moved"], merged_into_existing=merged_into_existing)

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
        self._reject_nom_prefix(tag_doc=canonical_tag)

        total_moved = 0
        sources_removed = 0

        for source_id in source_tag_ids:
            if source_id == canonical_tag_id:
                continue
            source_tag = self._get_tag_or_error(source_id)
            self._reject_nom_prefix(tag_doc=source_tag)

            relink = relink_tag_edges(self.db, int(source_id), int(canonical_tag_id))
            total_moved += relink["moved"]
            if relink["source_orphaned"]:
                sources_removed += 1

        song_ids = list_songs_for_tag(self.db, int(canonical_tag_id))
        for song_id in song_ids:
            transition_song_state(self.db, [int(song_id)], STATE_WRITTEN, STATE_NOT_WRITTEN)

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
        self._reject_nom_prefix(tag_doc=source_tag)

        target_tag_id = find_or_create_tag(self.db, source_tag["name"], new_value)
        new_tag_created = target_tag_id != int(source_tag_id)

        relink = relink_tag_edges(self.db, int(source_tag_id), target_tag_id, song_ids=[int(sid) for sid in song_ids])

        for song_id in song_ids:
            transition_song_state(self.db, [int(song_id)], STATE_WRITTEN, STATE_NOT_WRITTEN)

        return SplitResult(moved=relink["moved"], new_tag_created=new_tag_created)

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
        transition_song_state(self.db, [int(song_id)], STATE_WRITTEN, STATE_NOT_WRITTEN)
        tags = get_song_tags(self.db, int(song_id), name=name)
        if tags is None:
            tags_list: list[dict[str, Any]] = []
        else:
            tags_list = [
                {
                    "key": tag.name,
                    "value": str(value),
                    "type": "string",
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
