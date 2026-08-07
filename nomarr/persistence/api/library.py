"""Library persistence facade — thin namespaced forwarder.

``LibraryDb`` is the caller-facing entry point for the library persistence
surface. It holds no logic of its own: every public method delegates to one
of four domain-identity sub-facades (``files``, ``tags``, ``scans``,
``regions``) per DD-persistence-intent-facade-rebuild §Phase 1 (namespaced
forwarding). Callers keep using ``db.library.method()`` unchanged.

READ/WRITE classification (AR-2): the forwarder methods below carry no
guard themselves — enforcement lives in the sub-facades they delegate to
(see the classification blocks in ``library_files.py``, ``library_tags.py``,
``library_scans.py``, ``library_regions.py``). WRITE methods must be called
inside ``db.library.transaction()`` and raise :class:`FacadeMisuseError`
otherwise; READ methods use SQLAlchemy autobegin safely.

    files READ:   get_file, get_file_by_path, find_file_by_path_any_library,
                  list_files_by_ids, list_files, count_files,
                  get_library_ids_for_files, count_recently_tagged,
                  list_library_file_ids, list_songs, count_files_for_library,
                  find_library_file_by_chromaprint, list_existing_file_paths,
                  get_folder, list_folders_for_library, list_songs_for_folder,
                  list_tracks_for_matching, list_orphaned_file_ids
    files WRITE:  add_file_to_library, add_files_to_library, update_songs,
                  update_library_file_path, update_library_file_scan_metadata,
                  update_library_file_modified_time,
                  set_library_file_chromaprint,
                  update_library_file_last_tagged_at, update_file_fields,
                  remove_file, remove_file_by_path, add_library_folder,
                  remove_library_folder, replace_library_folders,
                  truncate_files, truncate_file_links, truncate_folder_links,
                  truncate_folders
    tags READ:    get_tag, list_tags_for_file, list_all_tag_names, list_tags,
                  count_tags, count_tags_filtered, list_tags_with_song_count,
                  list_tags_by_name, list_genre_tags_for_files,
                  list_file_tags_for_files, count_files_by_tag,
                  search_files_by_tag, search_files_by_tag_contains,
                  search_files_by_tag_pattern, list_file_ids_for_tag_id,
                  list_file_tag_edges, list_tag_value_frequencies,
                  list_orphaned_tag_ids
    tags WRITE:   find_or_create_tag, replace_file_tags, replace_tag_references,
                  replace_selected_tag_references, remove_file_tags,
                  delete_tags_by_ids, truncate_tags, truncate_song_tag_edges
    scans READ:   get_scan
    scans WRITE:  add_scan, update_scan, remove_scan, truncate_scan_records
    regions READ: get_library, get_library_by_name, list_libraries,
                  list_library_keys, get_pipeline_state,
                  get_libraries_in_axis_state
    regions WRITE: add_library, update_library, update_pipeline_axis,
                   remove_library
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import (
        LibraryFileRow,
        LibraryFolderRow,
        LibraryRow,
        LibraryScanRow,
        TagRow,
    )
    from nomarr.persistence.api.library_files import LibraryFilesDb
    from nomarr.persistence.api.library_regions import LibraryRegionsDb
    from nomarr.persistence.api.library_scans import LibraryScansDb
    from nomarr.persistence.api.library_tags import LibraryTagsDb


class LibraryDb:
    """Caller-facing library persistence facade (namespaced forwarder).

    Delegates each public method to the matching sub-facade: ``files``
    (file/folder domain), ``tags`` (tag/file-tag domain), ``scans`` (scan
    lifecycle), ``regions`` (library/pipeline-state domain).
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        files: LibraryFilesDb,
        tags: LibraryTagsDb,
        scans: LibraryScansDb,
        regions: LibraryRegionsDb,
    ) -> None:
        self._session = session
        self._files = files
        self._tags = tags
        self._scans = scans
        self._regions = regions

    def transaction(self) -> AbstractContextManager[Session]:
        """Return a ``session.begin()`` context manager for write operations (AR-2).

        Must be entered FIRST, before any write method call. If a read method
        already autobegun a transaction, warn and reuse it instead of ending it:
        committing an active transaction here would make SQLAlchemy raise
        ``InvalidRequestError`` on the next session use when the transaction was
        opened by an enclosing ``transaction()`` (``_trans_ctx_check`` rejects a
        closed-but-still-registered context manager), and an autobegun read
        transaction only needs to be committed by the returned context manager
        at exit. Reusing the active transaction is lossless and safe.
        """
        if cast("Session", self._session).in_transaction():
            warnings.warn(
                "Transaction already active — did you call a read method before entering the context?", stacklevel=2
            )
            active = cast("Session", self._session).get_transaction()
            if active is not None:
                return cast("AbstractContextManager[Session]", active)
        return cast("AbstractContextManager[Session]", self._session.begin())

    @property
    def files(self) -> LibraryFilesDb:
        """File and folder sub-facade."""
        return self._files

    @property
    def tags(self) -> LibraryTagsDb:
        """Tag and file-tag edge sub-facade."""
        return self._tags

    @property
    def scans(self) -> LibraryScansDb:
        """Scan lifecycle sub-facade."""
        return self._scans

    @property
    def regions(self) -> LibraryRegionsDb:
        """Library and pipeline-state sub-facade."""
        return self._regions

    # ------------------------------------------------------------------
    # Library / pipeline-state forwarding (regions)
    # ------------------------------------------------------------------

    def add_library(self, payload: dict[str, Any]) -> int:
        return self._regions.add_library(payload)

    def get_library(self, library_id: int) -> LibraryRow | None:
        return self._regions.get_library(library_id)

    def get_library_by_name(self, name: str) -> LibraryRow | None:
        return self._regions.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        return self._regions.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[int]:
        return self._regions.list_library_keys()

    def update_library(self, library_id: int, fields: dict[str, Any]) -> None:
        return self._regions.update_library(library_id, fields)

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        return self._regions.get_pipeline_state(library_id)

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        return self._regions.get_libraries_in_axis_state(axis_field, axis_value)

    def update_pipeline_axis(self, library_id: int, axis_field: str, axis_value: str) -> None:
        return self._regions.update_pipeline_axis(library_id, axis_field, axis_value)

    def remove_library(self, library_id: int) -> bool:
        return self._regions.remove_library(library_id)

    # ------------------------------------------------------------------
    # File / folder forwarding (files)
    # ------------------------------------------------------------------

    def get_file(self, file_id: int) -> LibraryFileRow | None:
        return self._files.get_file(file_id)

    def get_file_by_path(self, path: str, library_id: int) -> LibraryFileRow | None:
        return self._files.get_file_by_path(path, library_id)

    def find_file_by_path_any_library(self, path: str) -> LibraryFileRow | None:
        return self._files.find_file_by_path_any_library(path)

    def list_files_by_ids(self, file_ids: list[int]) -> list[LibraryFileRow]:
        return self._files.list_files_by_ids(file_ids)

    def list_files(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        return self._files.list_files(filters=filters, limit=limit)

    def count_files(self) -> int:
        return self._files.count_files()

    def get_library_ids_for_files(self, file_ids: list[int]) -> dict[int, int]:
        return self._files.get_library_ids_for_files(file_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        return self._files.count_recently_tagged(cutoff_ms)

    def list_library_file_ids(self, library_id: int, *, limit: int | None = None) -> list[int]:
        return self._files.list_library_file_ids(library_id, limit=limit)

    def list_songs(self, library_id: int, *, limit: int | None = None) -> list[LibraryFileRow]:
        return self._files.list_songs(library_id, limit=limit)

    def count_files_for_library(self, library_id: int) -> int:
        return self._files.count_files_for_library(library_id)

    def find_library_file_by_chromaprint(
        self,
        library_id: int,
        chromaprint: str,
    ) -> LibraryFileRow | None:
        return self._files.find_library_file_by_chromaprint(library_id, chromaprint)

    def add_file_to_library(self, library_id: int, payload: dict) -> int:
        return self._files.add_file_to_library(library_id, payload)

    def add_files_to_library(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        initial_state: str = "tagged",
    ) -> list[int]:
        return self._files.add_files_to_library(library_id, payloads, initial_state=initial_state)

    def update_songs(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        return self._files.update_songs(library_id, payloads, remove_missing=remove_missing)

    def update_library_file_path(self, file_id: int, new_path: str) -> None:
        return self._files.update_library_file_path(file_id, new_path)

    def update_library_file_scan_metadata(
        self,
        file_id: int,
        *,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        return self._files.update_library_file_scan_metadata(
            file_id,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=duration_seconds,
            normalized_path=normalized_path,
        )

    def update_library_file_modified_time(self, file_id: int, modified_time_ms: int) -> None:
        return self._files.update_library_file_modified_time(file_id, modified_time_ms)

    def set_library_file_chromaprint(self, file_id: int, chromaprint: str) -> None:
        return self._files.set_library_file_chromaprint(file_id, chromaprint)

    def update_library_file_last_tagged_at(self, file_id: int, tagged_at_ms: int) -> None:
        return self._files.update_library_file_last_tagged_at(file_id, tagged_at_ms)

    def update_file_fields(self, file_id: int, fields: dict[str, Any]) -> None:
        return self._files.update_file_fields(file_id, fields)

    def remove_file(self, file_id: int) -> None:
        return self._files.remove_file(file_id)

    def remove_file_by_path(self, path: str, library_id: int | None = None) -> None:
        return self._files.remove_file_by_path(path, library_id)

    def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        return self._files.list_existing_file_paths(paths)

    def get_folder(self, folder_id: int) -> LibraryFolderRow | None:
        return self._files.get_folder(folder_id)

    def list_folders_for_library(self, library_id: int) -> list[LibraryFolderRow]:
        return self._files.list_folders_for_library(library_id)

    def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        return self._files.add_library_folder(library_id, payload)

    def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        return self._files.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        return self._files.replace_library_folders(library_id, payloads)

    def list_songs_for_folder(
        self,
        library_id: int,
        folder_rel_path: str,
    ) -> list[LibraryFileRow]:
        return self._files.list_songs_for_folder(library_id, folder_rel_path)

    def list_tracks_for_matching(self, library_id: int, *, limit: int | None = None) -> list[LibraryFileRow]:
        return self._files.list_tracks_for_matching(library_id, limit=limit)

    # ------------------------------------------------------------------
    # Maintenance forwarding (files)
    # ------------------------------------------------------------------

    def list_orphaned_file_ids(self) -> list[int]:
        return self._files.list_orphaned_file_ids()

    def truncate_files(self) -> None:
        return self._files.truncate_files()

    def truncate_file_links(self) -> None:
        return self._files.truncate_file_links()

    def truncate_folder_links(self) -> None:
        return self._files.truncate_folder_links()

    def truncate_folders(self) -> None:
        return self._files.truncate_folders()

    # ------------------------------------------------------------------
    # Tag / file-tag forwarding (tags)
    # ------------------------------------------------------------------

    def get_tag(self, tag_id: int) -> TagRow | None:
        return self._tags.get_tag(tag_id)

    def find_or_create_tag(self, name: str, value: str, namespace: str) -> int:
        return self._tags.find_or_create_tag(name, value, namespace)

    def list_tags_for_file(self, file_id: int) -> list[TagRow]:
        return self._tags.list_tags_for_file(file_id)

    def list_all_tag_names(self, limit: int) -> list[str]:
        return self._tags.list_all_tag_names(limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagRow]:
        return self._tags.list_tags(name=name, value=value, limit=limit, offset=offset)

    def count_tags(self) -> int:
        return self._tags.count_tags()

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        return self._tags.count_tags_filtered(name=name, search=search)

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        return self._tags.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    def list_tags_by_name(self, name: str, limit: int) -> list[TagRow]:
        return self._tags.list_tags_by_name(name, limit)

    def list_genre_tags_for_files(self, file_ids: list[int]) -> list[TagRow]:
        return self._tags.list_genre_tags_for_files(file_ids)

    def list_file_tags_for_files(
        self,
        file_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> dict[int, list[TagRow]]:
        return self._tags.list_file_tags_for_files(file_ids, name_starts_with=name_starts_with)

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        return self._tags.count_files_by_tag(tag_key, target_value)

    def search_files_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[LibraryFileRow]:
        return self._tags.search_files_by_tag(tag_key, value, limit=limit)

    def search_files_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[LibraryFileRow]:
        return self._tags.search_files_by_tag_contains(tag_key, value, limit=limit)

    def search_files_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        return self._tags.search_files_by_tag_pattern(tag_name, pattern, limit=limit)

    def list_file_ids_for_tag_id(self, tag_id: int, *, limit: int | None, offset: int = 0) -> list[int]:
        return self._tags.list_file_ids_for_tag_id(tag_id, limit=limit, offset=offset)

    def list_file_tag_edges(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._tags.list_file_tag_edges(tag_ids, limit=limit)

    def replace_file_tags(self, file_id: int, tags: list[dict]) -> None:
        return self._tags.replace_file_tags(file_id, tags)

    def replace_tag_references(self, source_tag_id: int, target_tag_id: int) -> None:
        return self._tags.replace_tag_references(source_tag_id, target_tag_id)

    def replace_selected_tag_references(
        self,
        file_ids: list[int],
        source_tag_id: int,
        target_tag_id: int,
    ) -> None:
        return self._tags.replace_selected_tag_references(file_ids, source_tag_id, target_tag_id)

    def remove_file_tags(self, file_id: int, tag_keys: list[int] | None = None) -> None:
        return self._tags.remove_file_tags(file_id, tag_keys)

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        return self._tags.list_tag_value_frequencies(tag_names, limit)

    # ------------------------------------------------------------------
    # Maintenance forwarding (tags)
    # ------------------------------------------------------------------

    def list_orphaned_tag_ids(self) -> list[int]:
        return self._tags.list_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        return self._tags.delete_tags_by_ids(tag_ids)

    def truncate_tags(self) -> None:
        return self._tags.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        return self._tags.truncate_song_tag_edges()

    # ------------------------------------------------------------------
    # Scan forwarding (scans)
    # ------------------------------------------------------------------

    def get_scan(self, library_id: int) -> LibraryScanRow | None:
        return self._scans.get_scan(library_id)

    def add_scan(self, library_id: int, payload: dict[str, Any]) -> int:
        return self._scans.add_scan(library_id, payload)

    def update_scan(self, library_id: int, fields: dict[str, Any]) -> None:
        return self._scans.update_scan(library_id, fields)

    def remove_scan(self, library_id: int) -> None:
        return self._scans.remove_scan(library_id)

    def truncate_scan_records(self) -> None:
        return self._scans.truncate_scan_records()
