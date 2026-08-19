"""Tag sub-facade for the library persistence surface.

Holds all tag-domain (``tags`` table) and song-tag edge (``song_tags``
junction) intent methods. Wired into ``LibraryDb`` as its ``tags``
namespace (namespaced-forwarding split per
DD-persistence-intent-facade-rebuild §Phase 1). Methods moved verbatim
from ``LibraryDb`` — including the former maintenance surface —
signatures and behavior unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.repo_dto import SongRow, TagRow

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.persistence.database.song_tag_repo import SongTagRepository
    from nomarr.persistence.database.tag_repo import TagRepository


class LibraryTagsDb:
    """Persistence sub-facade for tag and song-tag edge operations.

    Domain identity: ``(name, value, namespace)`` tag natural key. Tag
    rows are keyed by their integer primary key internally; callers
    address tags by name/value/namespace where the intent method allows
    it.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        tag_repo: TagRepository,
        song_tag_repo: SongTagRepository,
    ) -> None:
        self._session = session
        self._tag_repo = tag_repo
        self._song_tag_repo = song_tag_repo

    # ------------------------------------------------------------------
    # Tag lookups
    # ------------------------------------------------------------------

    def get_tag(self, tag_id: int) -> TagRow | None:
        """Get a tag by its ID."""
        return self._tag_repo.get_tag(tag_id)

    def find_or_create_tag(self, name: str, value: str, namespace: str) -> int:
        """Return the ID of an existing tag or create a new one.

        Looks up a tag by its ``(name, value, namespace)`` triple.  If no
        matching row exists a new tag is inserted and its ID is returned.

        Args:
            name: Tag name (e.g. ``"nom:mood-strict"``).
            value: Tag value string.
            namespace: Tag namespace (empty string for the default namespace).

        Returns:
            The integer ID of the found or created tag row.

        """
        return self._tag_repo.get_or_create_tag(name, value, namespace)

    def list_tags_for_song(self, song_id: int) -> list[TagRow]:
        """Return all tags assigned to a song."""
        return self._song_tag_repo.get_tags_for_song(song_id)

    def list_all_tag_names(self, limit: int) -> list[str]:
        """Return distinct tag names, up to the given limit."""
        return self._tag_repo.list_all_tag_names(limit=limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagRow]:
        """Return tag rows matching the optional equality filters and paging arguments.

        Args:
            name: Optional tag name to match exactly.
            value: Optional tag value to match exactly.
            limit: Maximum number of tag rows to return.
            offset: Number of matching tag rows to skip.

        """
        return self._tag_repo.list_tags(name=name, value=value, limit=limit, offset=offset)

    def count_tags(self) -> int:
        """Return the total number of tag rows."""
        return self._tag_repo.count_tags()

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count tags matching name/search filters."""
        return self._tag_repo.count_tags_filtered(name=name, search=search)

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List tags with pre-computed song counts in a single query."""
        return self._tag_repo.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    def list_tags_by_name(self, name: str, limit: int) -> list[TagRow]:
        """Return tags matching an exact name, up to the given limit."""
        return self._tag_repo.list_tags(name=name, limit=limit)

    def list_genre_tags_for_songs(self, song_ids: list[int]) -> list[TagRow]:
        """Return genre tags assigned to any of the given songs."""
        return self._song_tag_repo.get_genre_tags_for_songs(song_ids)

    def list_song_tags_for_songs(
        self,
        song_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> dict[int, list[TagRow]]:
        """Return tags for many songs, grouped by song id.

        Uses a single batch read for all supplied songs. When
        ``name_starts_with`` is provided, only tags whose names start with that
        prefix are included.

        Args:
            song_ids: Songs whose tags should be fetched.
            name_starts_with: Optional prefix filter for tag names.

        Returns:
            A mapping from song id to the list of matching tag rows.

        """
        rows = self._song_tag_repo.get_tags_for_songs_batch(
            song_ids,
            name_starts_with=name_starts_with,
        )
        grouped: dict[int, list[TagRow]] = {sid: [] for sid in song_ids}
        for row in rows:
            sid = row.get("song_id")
            if not isinstance(sid, int):
                continue
            tag_row = TagRow(
                id=row["tag_id"],
                name=row["tag_name"],
                value=row["tag_value"],
                namespace=row.get("namespace", ""),
                parent_tag_id=row.get("parent_tag_id"),
                source=row.get("source", ""),
                confidence=row.get("confidence"),
                tier=row.get("tier"),
                created_at=row.get("created_at", 0),
            )
            grouped.setdefault(sid, []).append(tag_row)
        return grouped

    def count_songs_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count songs that have a tag with the given key and value."""
        return self._song_tag_repo.count_songs_by_tag(tag_key, target_value)

    def search_songs_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[SongRow]:
        """Search for songs with an exact tag key/value match."""
        return self._song_tag_repo.search_songs_by_tag(tag_key, value, limit=limit)

    def search_songs_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[SongRow]:
        """Return songs whose tag value contains *value* (ILIKE substring match).

        Args:
            tag_key: Tag name to search for (e.g., "nom:mood-strict").
            value: Substring to match within the tag's value string.
            limit: Maximum number of song rows to return.

        Returns:
            List of song rows that have a tag with the given key whose value
            contains *value* (case-insensitive).

        """
        return self._song_tag_repo.search_songs_by_tag_contains(tag_key, value, limit=limit)

    def search_songs_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return songs whose tag value matches an ILIKE *pattern*.

        Joins library songs to their tag edges and tag rows, filtering on
        exact ``tag_name`` match and ILIKE ``pattern`` against the tag value.

        Args:
            tag_name: Tag name to match exactly (e.g. ``"artist"``).
            pattern: SQL ILIKE pattern for the tag value (e.g. ``"%Beatles%"``).
            limit: Optional maximum number of song rows to return.

        Returns:
            List of matching :class:`SongRow` dicts.

        """
        return self._song_tag_repo.search_songs_by_tag_pattern(tag_name, pattern, limit=limit)

    def list_song_ids_for_tag_id(self, tag_id: int, *, limit: int | None, offset: int = 0) -> list[int]:
        """Return song IDs assigned to a tag, with paging."""
        return self._song_tag_repo.list_song_ids_for_tag(tag_id, limit=limit, offset=offset)

    def list_song_tag_edges(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return song-tag edge rows for the given tag IDs.

        Each returned dict contains ``song_id``, ``tag_id``, ``confidence``,
        and ``source`` keys.

        Args:
            tag_ids: Tag IDs whose edges should be returned.
            limit: Optional maximum number of edges to return.

        Returns:
            List of edge dicts.

        """
        return self._song_tag_repo.get_song_tag_edges_for_tags(tag_ids, limit=limit)

    # ------------------------------------------------------------------
    # Song-tag mutations
    # ------------------------------------------------------------------

    def replace_song_tags(self, song_id: int, tags: list[dict]) -> None:
        """Replace all tag associations for a song.

        Callers provide tag documents using the public ``name``/``value``
        shape.  Resolve documents without an existing database ID before
        delegating to the junction-table repository, whose contract is
        intentionally ID-based.
        """
        resolved_tags: list[dict[str, Any]] = []
        for tag in tags:
            tag_id = tag.get("tag_id", tag.get("id"))
            if not isinstance(tag_id, int):
                name = tag["name"]
                value = tag["value"]
                tag_id = self.find_or_create_tag(str(name), str(value), str(tag.get("namespace", "")))
            resolved_tag = dict(tag)
            resolved_tag["tag_id"] = tag_id
            resolved_tags.append(resolved_tag)
        self._song_tag_repo.replace_song_tags(song_id, resolved_tags)

    def replace_tag_references(self, source_tag_id: int, target_tag_id: int) -> None:
        """Remap song→tag edges from one tag to another across all affected songs."""
        self._song_tag_repo.replace_tag_references(source_tag_id, target_tag_id)

    def replace_selected_tag_references(
        self,
        song_ids: list[int],
        source_tag_id: int,
        target_tag_id: int,
    ) -> None:
        """Remap song→tag edges for a selected set of songs."""
        self._song_tag_repo.replace_tag_references(
            source_tag_id,
            target_tag_id,
            song_ids=song_ids,
        )

    def remove_song_tags(self, song_id: int, tag_keys: list[int] | None = None) -> None:
        """Remove tag edges for one song and clean up orphaned tags."""
        if tag_keys is None:
            self._song_tag_repo.replace_song_tags(song_id, [])
        else:
            self._song_tag_repo.remove_tags_from_song(song_id, tag_keys)
        self._tag_repo.cleanup_orphaned_tags()

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        """Return value frequency distributions for the given tag names."""
        return self._tag_repo.get_tag_value_frequencies_batch(tag_names, limit=limit)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def list_orphaned_tag_ids(self) -> list[int]:
        """List tag IDs that have no matching song assignment."""
        return self._tag_repo.get_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        """Delete tags by their IDs.

        Returns:
            The number of tags deleted.

        """
        return self._tag_repo.delete_tags_by_ids(tag_ids)

    def truncate_tags(self) -> None:
        """Remove all tag rows."""
        return self._tag_repo.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        """Remove all song-to-tag assignment edges."""
        return self._song_tag_repo.truncate_song_tag_assignments()
