"""Tag sub-facade for the library persistence surface.

Holds all tag-domain (``tags`` table) and file-tag edge (``file_tags``
junction) intent methods. Wired into ``LibraryDb`` as its ``tags``
namespace (namespaced-forwarding split per
DD-persistence-intent-facade-rebuild §Phase 1). Methods moved verbatim
from ``LibraryDb`` — including the former maintenance surface —
signatures and behavior unchanged.

READ/WRITE classification (AR-2): READ methods use SQLAlchemy autobegin
and need no transaction context; WRITE methods (inserts/updates/deletes/
upserts/truncates) must be called inside ``LibraryDb.transaction()`` and
raise :class:`FacadeMisuseError` otherwise.

READ:   get_tag, list_tags_for_file, list_all_tag_names, list_tags,
        count_tags, count_tags_filtered, list_tags_with_song_count,
        list_tags_by_name, list_genre_tags_for_files, list_file_tags_for_files,
        count_files_by_tag, search_files_by_tag, search_files_by_tag_contains,
        search_files_by_tag_pattern, list_file_ids_for_tag_id,
        list_file_tag_edges, list_tag_value_frequencies, list_orphaned_tag_ids
WRITE:  find_or_create_tag, replace_file_tags, replace_tag_references,
        replace_selected_tag_references, remove_file_tags, delete_tags_by_ids,
        truncate_tags, truncate_song_tag_edges
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.repo_dto import LibraryFileRow, TagRow
from nomarr.helpers.exceptions import FacadeMisuseError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.persistence.database.file_tag_repo import FileTagRepository
    from nomarr.persistence.database.tag_repo import TagRepository


class LibraryTagsDb:
    """Persistence sub-facade for tag and file-tag edge operations.

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
        file_tag_repo: FileTagRepository,
    ) -> None:
        self._session = session
        self._tag_repo = tag_repo
        self._file_tag_repo = file_tag_repo

    def _require_transaction(self, method_name: str) -> None:
        """Raise :class:`FacadeMisuseError` when no transaction is active (AR-2)."""
        if not cast("Session", self._session).in_transaction():
            raise FacadeMisuseError(
                f"{type(self).__name__}.{method_name}() is a write method — call within a transaction() context"
            )

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
        self._require_transaction("find_or_create_tag")
        return self._tag_repo.get_or_create_tag(name, value, namespace)

    def list_tags_for_file(self, file_id: int) -> list[TagRow]:
        """Return all tags assigned to a file."""
        return self._file_tag_repo.get_tags_for_file(file_id)

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

    def list_genre_tags_for_files(self, file_ids: list[int]) -> list[TagRow]:
        """Return genre tags assigned to any of the given files."""
        return self._file_tag_repo.get_genre_tags_for_files(file_ids)

    def list_file_tags_for_files(
        self,
        file_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> dict[int, list[TagRow]]:
        """Return tags for many files, grouped by file id.

        Uses a single batch read for all supplied files. When
        ``name_starts_with`` is provided, only tags whose names start with that
        prefix are included.

        Args:
            file_ids: Files whose tags should be fetched.
            name_starts_with: Optional prefix filter for tag names.

        Returns:
            A mapping from file id to the list of matching tag rows.

        """
        rows = self._file_tag_repo.get_tags_for_files_batch(
            file_ids,
            name_starts_with=name_starts_with,
        )
        grouped: dict[int, list[TagRow]] = {fid: [] for fid in file_ids}
        for row in rows:
            fid = row.get("file_id")
            if not isinstance(fid, int):
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
            grouped.setdefault(fid, []).append(tag_row)
        return grouped

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count files that have a tag with the given key and value."""
        return self._file_tag_repo.count_files_by_tag(tag_key, target_value)

    def search_files_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[LibraryFileRow]:
        """Search for files with an exact tag key/value match."""
        return self._file_tag_repo.search_files_by_tag(tag_key, value, limit=limit)

    def search_files_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[LibraryFileRow]:
        """Return files whose tag value contains *value* (ILIKE substring match).

        Args:
            tag_key: Tag name to search for (e.g., "nom:mood-strict").
            value: Substring to match within the tag's value string.
            limit: Maximum number of file rows to return.

        Returns:
            List of file rows that have a tag with the given key whose value
            contains *value* (case-insensitive).

        """
        return self._file_tag_repo.search_files_by_tag_contains(tag_key, value, limit=limit)

    def search_files_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return files whose tag value matches an ILIKE *pattern*.

        Joins library files to their tag edges and tag rows, filtering on
        exact ``tag_name`` match and ILIKE ``pattern`` against the tag value.

        Args:
            tag_name: Tag name to match exactly (e.g. ``"artist"``).
            pattern: SQL ILIKE pattern for the tag value (e.g. ``"%Beatles%"``).
            limit: Optional maximum number of file rows to return.

        Returns:
            List of matching :class:`LibraryFileRow` dicts.

        """
        return self._file_tag_repo.search_files_by_tag_pattern(tag_name, pattern, limit=limit)

    def list_file_ids_for_tag_id(self, tag_id: int, *, limit: int | None, offset: int = 0) -> list[int]:
        """Return file IDs assigned to a tag, with paging."""
        return self._file_tag_repo.list_file_ids_for_tag(tag_id, limit=limit, offset=offset)

    def list_file_tag_edges(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return file-tag edge rows for the given tag IDs.

        Each returned dict contains ``file_id``, ``tag_id``, ``confidence``,
        and ``source`` keys.

        Args:
            tag_ids: Tag IDs whose edges should be returned.
            limit: Optional maximum number of edges to return.

        Returns:
            List of edge dicts.

        """
        return self._file_tag_repo.get_file_tag_edges_for_tags(tag_ids, limit=limit)

    # ------------------------------------------------------------------
    # File-tag mutations
    # ------------------------------------------------------------------

    def replace_file_tags(self, file_id: int, tags: list[dict]) -> None:
        """Replace all tag associations for a file."""
        self._require_transaction("replace_file_tags")
        self._file_tag_repo.replace_file_tags(file_id, tags)

    def replace_tag_references(self, source_tag_id: int, target_tag_id: int) -> None:
        """Remap song→tag edges from one tag to another across all affected files."""
        self._require_transaction("replace_tag_references")
        self._file_tag_repo.replace_tag_references(source_tag_id, target_tag_id)

    def replace_selected_tag_references(
        self,
        file_ids: list[int],
        source_tag_id: int,
        target_tag_id: int,
    ) -> None:
        """Remap song→tag edges for a selected set of files."""
        self._require_transaction("replace_selected_tag_references")
        self._file_tag_repo.replace_tag_references(
            source_tag_id,
            target_tag_id,
            file_ids=file_ids,
        )

    def remove_file_tags(self, file_id: int, tag_keys: list[int] | None = None) -> None:
        """Remove tag edges for one file and clean up orphaned tags."""
        self._require_transaction("remove_file_tags")
        if tag_keys:
            for tag_id in tag_keys:
                self._file_tag_repo.remove_tag_from_file(file_id, tag_id)
        self._tag_repo.cleanup_orphaned_tags()

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        """Return value frequency distributions for the given tag names."""
        return self._tag_repo.get_tag_value_frequencies_batch(tag_names, limit=limit)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def list_orphaned_tag_ids(self) -> list[int]:
        """List tag IDs that have no matching file assignment."""
        return self._tag_repo.get_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        """Delete tags by their IDs.

        Returns:
            The number of tags deleted.

        """
        self._require_transaction("delete_tags_by_ids")
        return self._tag_repo.delete_tags_by_ids(tag_ids)

    def truncate_tags(self) -> None:
        """Remove all tag rows."""
        self._require_transaction("truncate_tags")
        return self._tag_repo.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        """Remove all file-to-tag assignment edges."""
        self._require_transaction("truncate_song_tag_edges")
        return self._file_tag_repo.truncate_file_tag_assignments()
