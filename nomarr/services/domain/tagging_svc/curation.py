"""Tag curation operations for TaggingService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_query_comp import _locators_for_songs
from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.tagging.tag_query_comp import _assignments_to_tags
from nomarr.components.tagging.tag_write_comp import relink_tag_edges, set_song_tags
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.dto.tag_curation_dto import MergeResult, RenameResult, SplitResult
from nomarr.helpers.song_locator_codec import decode_song_locator

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

# NOTE (Q3-C/K handoff): this service imports two private carriers-to-locator
# helpers cross-module -- ``_locators_for_songs`` (library_song_query_comp) and
# ``_assignments_to_tags`` (tag_query_comp) -- because the public carrier->
# SongLocator projection (CONTRACTS §3.1) is owned by Q3-C/K and does not exist
# yet. CONTRACTS §3.1 states Plan K "must not ... expose _locators_for_songs",
# so when K publishes that public projection these imports must be unwound and
# replaced. This is a classified residual for Q3-C/K; no shim, alias, or public
# projection is built here.


class TaggingCurationMixin:
    """Mixin providing tag curation methods."""

    db: Database

    def _mark_song_write_pending(self, song: SongIdentity) -> None:
        """Queue a curated song for both projection and file write-back."""
        transition_song_state(self.db, [song], STATE_WRITTEN, STATE_NOT_WRITTEN)
        if STATE_TAGS_CURRENT in self.db.app.song_state_membership(song):
            transition_song_state(self.db, [song], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)

    def _song_identity_from_token(self, token: str) -> SongIdentity:
        """Resolve one opaque ``nom1`` SongLocator token to its semantic locator.

        The wire boundary owns the token format; the service resolves the decoded
        ``library_uuid`` to the owning library through the canonical facade and
        builds the request-scoped ``SongIdentity``. No generated integer identity
        and no ``resolve_song_identity`` bridge participates. An unknown library
        is a deterministic not-found ``ValueError``.
        """
        payload = decode_song_locator(token)
        library = self.db.library.get_library_by_uuid(payload.library_uuid)
        if library is None:
            msg = f"Unknown library for song locator: {payload.library_uuid}"
            raise ValueError(msg)
        return SongIdentity(
            library=LibraryIdentity(
                library_uuid=payload.library_uuid,
                name=library.name,
                root_path=library.root_path,
            ),
            normalized_path=payload.path,
        )

    def _mark_matched_songs_write_pending(self, tag: TagRef) -> None:
        """Mark every located song carrying ``tag`` as write-pending.

        ``find_songs_with_tag`` returns bare semantic songs without their owning
        library; locators are recovered through the shared read projection and
        unresolved (stale) songs are skipped rather than re-addressed by guesswork.
        """
        songs = list(self.db.library.find_songs_with_tag(tag, limit=None))
        for locator in _locators_for_songs(self.db, songs):
            if locator is not None:
                self._mark_song_write_pending(locator)

    @staticmethod
    def _reject_nom_prefix(name: str | None = None, *, identity: TagRef | None = None) -> None:
        """Raise ValueError if the tag or name has the read-only nom: prefix (ADR-009)."""
        if name is not None and name.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: name={name}"
            raise ValueError(msg)
        if identity is not None and identity.name.startswith("nom:"):
            msg = f"Tags with 'nom:' prefix are read-only and cannot be edited: {identity.name}={identity.value}"
            raise ValueError(msg)

    def _get_tag_or_error(self, identity: TagRef) -> TagRef:
        """Resolve a complete natural tag identity via the facade, or raise ValueError.

        The interface boundary owns decoding an opaque handle to ``TagRef`` before
        this service is called, so ``identity`` is already the complete natural
        (name, value, namespace) key. This helper verifies that natural tag still
        exists in the database through ``db.library.get_tag`` -- never a storage
        primary key, never ``int()`` conversion, never the root tag bridge. A
        missing natural identity is a deterministic not-found ``ValueError`` that
        the interface maps to its existing 400/404 policy.
        """
        resolved = self.db.library.get_tag(identity)
        if resolved is None:
            msg = f"Tag not found: {identity.name}={identity.value}"
            raise ValueError(msg)
        return resolved

    def rename_tag(self, source_tag: TagRef, new_value: str) -> RenameResult:
        """Rename a tag to a new value.

        Rejects nom: prefix tags (ADR-009). Creates target tag if needed,
        then relinks all edges from source to target.

        Args:
            source_tag: Complete natural identity of the source tag (``TagRef``).
                The interface decodes an opaque handle to ``TagRef`` before calling.
            new_value: New value for the tag

        Returns:
            RenameResult with moved count and whether it merged into existing

        Raises:
            ValueError: If tag not found or has nom: prefix

        """
        source_tag = self._get_tag_or_error(source_tag)
        self._reject_nom_prefix(identity=source_tag)

        target_identity = self.db.library.ensure_tag(TagRef(name=source_tag.name, value=new_value, namespace="default"))
        merged_into_existing = target_identity != source_tag

        relink = relink_tag_edges(self.db, source_tag, target_identity)

        self._mark_matched_songs_write_pending(target_identity)

        return RenameResult(moved=relink.moved, merged_into_existing=merged_into_existing)

    def merge_tags(self, source_tags: list[TagRef], canonical_tag: TagRef) -> MergeResult:
        """Merge multiple source tags into a canonical tag.

        Rejects nom: prefix tags (ADR-009). Iterates each source through
        relink_tag_edges to the canonical target.

        Args:
            source_tags: Complete natural identities of the tags to merge FROM.
            canonical_tag: Complete natural identity of the tag to merge INTO.

        Returns:
            MergeResult with total_moved and sources_removed counts

        Raises:
            ValueError: If any tag not found or has nom: prefix

        """
        canonical_tag = self._get_tag_or_error(canonical_tag)
        self._reject_nom_prefix(identity=canonical_tag)

        total_moved = 0
        sources_removed = 0

        for source_tag in source_tags:
            if source_tag == canonical_tag:
                continue
            source_tag = self._get_tag_or_error(source_tag)
            self._reject_nom_prefix(identity=source_tag)

            relink = relink_tag_edges(self.db, source_tag, canonical_tag)
            total_moved += relink.moved
            if relink.source_orphaned:
                sources_removed += 1

        self._mark_matched_songs_write_pending(canonical_tag)

        return MergeResult(total_moved=total_moved, sources_removed=sources_removed)

    def split_tag(self, source_tag: TagRef, song_ids: list[str], new_value: str) -> SplitResult:
        """Split selected songs from a tag into a new tag value.

        Rejects nom: prefix tags (ADR-009). Creates a new tag with the given
        value and relinks only the specified songs.

        Args:
            source_tag: Complete natural identity of the source tag to split FROM.
                The interface decodes an opaque handle to ``TagRef`` before calling.
            song_ids: Opaque ``nom1`` SongLocator tokens naming the songs to move
                to the new tag. Each token is decoded via
                ``_song_identity_from_token`` to a semantic ``SongIdentity``;
                there is no integer/resolver reinterpretation and no fallback.
            new_value: Value for the new tag

        Returns:
            SplitResult with moved count and whether a new tag was created

        Raises:
            ValueError: If tag not found, has nom: prefix, or a token names an
                unknown library.

        """
        source_tag = self._get_tag_or_error(source_tag)
        self._reject_nom_prefix(identity=source_tag)

        target_identity = self.db.library.ensure_tag(TagRef(name=source_tag.name, value=new_value, namespace="default"))
        new_tag_created = target_identity != source_tag

        song_identities = [self._song_identity_from_token(token) for token in song_ids]
        relink = relink_tag_edges(
            self.db,
            source_tag,
            target_identity,
            song_identities=song_identities,
        )

        for song in song_identities:
            self._mark_song_write_pending(song)

        return SplitResult(moved=relink.moved, new_tag_created=new_tag_created)

    def update_song_tags(self, song_id: str, name: str, values: list[str]) -> dict:
        """Update the value of a single tag on a song.

        Args:
            song_id: Opaque ``nom1`` SongLocator token for the target song.
            name: The tag name to update.
            values: The new values to assign.

        Returns:
            A dict keyed by ``file_id`` (API contract), ``name`` and ``tags``.
        """
        self._reject_nom_prefix(name=name)
        song = self._song_identity_from_token(song_id)
        set_song_tags(self.db, song, name, list(values))
        self._mark_song_write_pending(song)
        assignments = self.db.library.list_tags_for_song(song)
        matching = [assignment for assignment in assignments if assignment.name == name]
        tags = _assignments_to_tags(matching) if matching else None
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
