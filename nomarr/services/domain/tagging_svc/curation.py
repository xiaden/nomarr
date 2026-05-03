"""Tag curation operations for TaggingService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_state_comp import transition_file_state
from nomarr.components.tagging.tag_query_comp import get_song_tags, get_tag, list_songs_for_tag
from nomarr.components.tagging.tag_write_comp import find_or_create_tag, relink_tag_edges, set_song_tags
from nomarr.helpers.constants.file_states import STATE_TAGS_NOT_WRITTEN, STATE_TAGS_WRITTEN
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
        tag = get_tag(self.db, tag_id)
        if not tag:
            msg = f"Tag not found: {tag_id}"
            raise ValueError(msg)
        return tag

    def rename_tag(self, tag_id: str, new_value: str) -> RenameResult:
        """Rename a tag to a new value.

        Rejects nom: prefix tags (ADR-009). Creates target tag if needed,
        then relinks all edges from source to target.

        Args:
            tag_id: Source tag _id (e.g., "tags/12345")
            new_value: New value for the tag

        Returns:
            RenameResult with moved count and whether it merged into existing

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(tag_id)
        self._reject_nom_prefix(tag_doc=source_tag)

        target_tag_id = find_or_create_tag(self.db, source_tag["name"], new_value)
        merged_into_existing = target_tag_id != tag_id

        relink = relink_tag_edges(self.db, tag_id, target_tag_id)

        song_ids = list_songs_for_tag(self.db, target_tag_id)
        for song_id in song_ids:
            transition_file_state(self.db, [song_id], STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN)

        return RenameResult(moved=relink["moved"], merged_into_existing=merged_into_existing)

    def merge_tags(self, source_tag_ids: list[str], canonical_tag_id: str) -> MergeResult:
        """Merge multiple source tags into a canonical tag.

        Rejects nom: prefix tags (ADR-009). Iterates each source through
        relink_tag_edges to the canonical target.

        Args:
            source_tag_ids: Tag _ids to merge FROM
            canonical_tag_id: Tag _id to merge INTO

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

            relink = relink_tag_edges(self.db, source_id, canonical_tag_id)
            total_moved += relink["moved"]
            if relink["source_orphaned"]:
                sources_removed += 1

        song_ids = list_songs_for_tag(self.db, canonical_tag_id)
        for song_id in song_ids:
            transition_file_state(self.db, [song_id], STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN)

        return MergeResult(total_moved=total_moved, sources_removed=sources_removed)

    def split_tag(self, source_tag_id: str, song_ids: list[str], new_value: str) -> SplitResult:
        """Split selected songs from a tag into a new tag value.

        Rejects nom: prefix tags (ADR-009). Creates a new tag with the given
        value and relinks only the specified songs.

        Args:
            source_tag_id: Tag _id to split FROM
            song_ids: Song _ids to move to the new tag
            new_value: Value for the new tag

        Returns:
            SplitResult with moved count and whether a new tag was created

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(source_tag_id)
        self._reject_nom_prefix(tag_doc=source_tag)

        target_tag_id = find_or_create_tag(self.db, source_tag["name"], new_value)
        new_tag_created = target_tag_id != source_tag_id

        relink = relink_tag_edges(self.db, source_tag_id, target_tag_id, song_ids=song_ids)

        for song_id in song_ids:
            transition_file_state(self.db, [song_id], STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN)

        return SplitResult(moved=relink["moved"], new_tag_created=new_tag_created)

    def update_file_tags(self, file_id: str, name: str, values: list[str]) -> dict[str, Any]:
        """Replace all tags for a file+name with new values.

        Rejects nom: prefix names (ADR-009). Delegates to set_song_tags
        and marks the file for writeback.

        Args:
            file_id: Library file _id
            name: Tag key (e.g., "genre", "artist")
            values: New tag values

        Returns:
            Dict with updated tags

        Raises:
            ValueError: If name has nom: prefix

        """
        self._reject_nom_prefix(name=name)
        set_song_tags(self.db, file_id, name, list(values))
        transition_file_state(self.db, [file_id], STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN)
        tags = get_song_tags(self.db, file_id, name=name)
        return {"file_id": file_id, "name": name, "tags": tags.to_dict()}
