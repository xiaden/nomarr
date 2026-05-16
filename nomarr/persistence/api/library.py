from __future__ import annotations

from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.database.file_states_aql import FileStatesAqlOperations
from nomarr.persistence.database.libraries_aql import LibrariesAqlOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations
from nomarr.persistence.database.ml_streams_aql import MlStreamsAqlOperations
from nomarr.persistence.database.scan_aql import ScanAqlOperations
from nomarr.persistence.database.tags_aql import TagsAqlOperations
from nomarr.persistence.database.vectors_aql import VectorsAqlOperations


class LibraryMaintenanceDb:
    """Maintenance-only companion surface for library persistence operations.

    Wired as ``LibraryDb.maintenance`` by Part A. Destructive, reset, repair,
    and diagnostics-only operations belong here, not on the routine top-level
    ``LibraryDb`` surface. Parts B/E add new maintenance methods here and
    clean up any remaining top-level shims.
    """

    def __init__(
        self,
        *,
        files: LibraryFilesAqlOperations,
        tags: TagsAqlOperations,
    ) -> None:
        self._files = files
        self._tags = tags

    def list_orphaned_file_ids(self) -> list[str]:
        return self._files.list_orphaned_file_ids()

    def list_orphaned_tag_ids(self) -> list[str]:
        return self._tags.get_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[str]) -> int:
        return self._tags.delete_tags_by_ids(tag_ids)

    def truncate_files(self) -> None:
        return self._files.truncate_files()

    def truncate_file_links(self) -> None:
        return self._files.truncate_file_links()

    def truncate_folder_links(self) -> None:
        return self._files.truncate_folder_links()

    def truncate_folders(self) -> None:
        return self._files.truncate_folders()

    def truncate_tags(self) -> None:
        return self._tags.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        return self._tags.truncate_song_tag_edges()


class LibraryDb:
    """Persistence sub-facade for library, file, tag, and scan operations.

    Routine callers use the normalized library intent methods on this facade.
    Maintenance operations live on ``.maintenance`` (a
    ``LibraryMaintenanceDb`` instance) instead of the routine top-level API.

    Part B authoritative migration map for this facade:
    - Final routine API: ``add_file_to_library``, ``add_files_to_library``,
      ``update_library_files``, ``update_library_file_path``, ``remove_file``,
      ``remove_file_by_path``, ``replace_file_tags``,
      ``replace_tag_references``, ``replace_selected_tag_references``,
      ``remove_file_tags``, ``list_file_tags_for_files``,
      ``add_library_folder``, ``remove_library_folder``,
      ``replace_library_folders``, ``find_file_by_path_any_library``,
      ``list_files_by_ids``, ``list_tags_for_file``, ``list_tags_by_name``,
      ``list_genre_tags_for_files``, ``list_tracks_for_matching``, and
      ``list_tag_value_frequencies``.
    - Temporary forwarding shims: a small set of legacy pre-normalized or
      low-level names remain only for caller migration under the Part A policy.
    - Maintenance-only: orphan cleanup and truncate/reset routines remain on
      ``.maintenance`` and are exposed top-level only as explicit temporary shims.
    """

    def __init__(
        self,
        *,
        libraries: LibrariesAqlOperations,
        files: LibraryFilesAqlOperations,
        tags: TagsAqlOperations,
        scan: ScanAqlOperations,
        file_states: FileStatesAqlOperations | None = None,
        streams: MlStreamsAqlOperations | None = None,
        vectors: VectorsAqlOperations | None = None,
    ) -> None:
        self._libraries = libraries
        self._files = files
        self._tags = tags
        self._scan = scan
        raw_db = cast("Any", getattr(files, "_db", None))
        self._file_states = file_states or FileStatesAqlOperations(raw_db)
        self._streams = streams or MlStreamsAqlOperations(raw_db)
        self._vectors = vectors or VectorsAqlOperations(raw_db)
        self.maintenance: LibraryMaintenanceDb = LibraryMaintenanceDb(
            files=files,
            tags=tags,
        )

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    def add_library(self, payload: dict) -> str:
        return self._libraries.add_library(payload)

    def get_library(self, library_id: str) -> dict | None:
        return self._libraries.get_library(library_id)

    def get_library_by_name(self, name: str) -> dict | None:
        return self._libraries.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[dict]:
        return self._libraries.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[str]:
        return self._libraries.list_library_keys()

    def update_library(self, library_id: str, fields: dict) -> None:
        return self._libraries.update_library(library_id, fields)

    def get_file(self, file_id: str) -> dict | None:
        return self._files.get_file(file_id)

    def get_file_by_path(self, path: str, library_id: str) -> dict | None:
        return self._files.get_file_by_path(path, library_id)

    def find_file_by_path_any_library(self, path: str) -> dict | None:
        return self._files.get_file_by_path_unscoped(path)

    def list_files_by_ids(self, file_ids: list[str]) -> list[dict]:
        return self._files.get_files_by_ids(file_ids)

    def list_files(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return library file documents matching the optional filters and limit."""
        return self._files.list_files(filters=filters, limit=limit)

    def count_files(self) -> int:
        return self._files.count_files()

    def get_library_ids_for_files(self, file_ids: list[str]) -> dict[str, str]:
        """Return mapping of file_id → library_id for the given file IDs."""
        return self._files.get_library_ids_for_files(file_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        return self._files.count_recently_tagged(cutoff_ms)

    def search_files_by_text(
        self,
        field_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._files.search_files_by_text(field_name, pattern, limit=limit)

    def list_library_file_ids(
        self,
        library_id: str,
        *,
        limit: int | None = None,
    ) -> list[str]:
        return self._files.list_library_file_ids(library_id, limit=limit)

    def list_library_files(
        self,
        library_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._files.list_library_files(library_id, limit=limit)

    def find_library_file_by_chromaprint(
        self,
        library_id: str,
        chromaprint: str,
    ) -> dict | None:
        return self._files.find_library_file_by_chromaprint(library_id, chromaprint)

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        return self._files.count_files_by_tag(tag_key, target_value)

    def search_files_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[dict]:
        return self._tags.search_files_by_tag(tag_key, value, limit=limit)

    def list_file_ids_for_tag_id(self, tag_id: str, *, limit: int | None, offset: int = 0) -> list[str]:
        return self._tags.list_file_ids_for_tag_id(tag_id, limit=limit, offset=offset)

    def get_tag(self, tag_id: str) -> dict | None:
        return self._tags.get_tag(tag_id)

    def list_tags_for_file(self, file_id: str) -> list[dict]:
        return self._tags.get_tags_for_file(file_id)

    def list_all_tag_names(self, limit: int) -> list[str]:
        return self._tags.list_all_tag_names(limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """Return tag documents matching the optional equality filters and paging arguments.

        Args:
            name: Optional tag name to match exactly.
            value: Optional tag value to match exactly.
            limit: Maximum number of tag documents to return.
            offset: Number of matching tag documents to skip.
        """
        return self._tags.list_tags(name=name, value=value, limit=limit, offset=offset)

    def count_tags(self) -> int:
        return self._tags.count_tags()

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count tags matching name/search filters."""
        return self._tags.count_tags_filtered(name=name, search=search)

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List tags with pre-computed song counts in a single AQL query."""
        return self._tags.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    def list_tags_by_name(self, name: str, limit: int) -> list[dict]:
        return self._tags.get_tags_by_name(name, limit)

    def list_genre_tags_for_files(self, file_ids: list[str]) -> list[dict]:
        return self._tags.get_genre_tags_for_files(file_ids)

    def list_file_tags_for_files(
        self,
        file_ids: list[str],
        *,
        name_starts_with: str | None = None,
    ) -> dict[str, list[dict]]:
        """Return tags for many files, grouped by file id.

        Uses a single batch read for all supplied files. When
        ``name_starts_with`` is provided, only tags whose names start with that
        prefix are included.

        Args:
            file_ids: Files whose tags should be fetched.
            name_starts_with: Optional prefix filter for tag names.

        Returns:
            A mapping from file id to the list of matching tag documents.
        """
        grouped_tags: dict[str, list[dict]] = {file_id: [] for file_id in file_ids}
        rows = self._tags.get_tags_for_files_batch(
            file_ids,
            name_starts_with=name_starts_with,
            include_edge=False,
        )
        for row in rows:
            file_id = row.get("start_id")
            tag_doc = row.get("v")
            if not isinstance(file_id, str) or not isinstance(tag_doc, dict):
                continue
            grouped_tags.setdefault(file_id, []).append(tag_doc)
        return grouped_tags

    def get_folder(self, folder_id: str) -> dict | None:
        return self._files.get_folder(folder_id)

    def list_folders_for_library(self, library_id: str) -> list[dict]:
        return self._files.list_folders_for_library(library_id)

    def list_tracks_for_matching(
        self,
        library_id: str,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._files.get_tracks_for_matching(library_id, limit=limit)

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        return {tag_name: self._tags.get_tag_value_frequencies(tag_name, limit=limit) for tag_name in tag_names}

    def remove_library(self, library_id: str) -> bool:
        """Delete a library and all associated data.

        Returns True if the library was found and deleted, False if not found.
        Delegates to the hand-written AQL cascade in LibrariesAqlOperations.
        Orphaned tag documents are not cleaned up — callers should invoke
        cleanup_orphaned_tags() separately if needed.
        """
        if not self._libraries.get_library(library_id):
            return False
        self._libraries.remove_library(library_id)
        return True

    def add_file_to_library(self, library_id: str, payload: dict) -> str:
        """Insert or update one library-file document and initialize its state edges.

        Returns the ``_id`` of the upserted document.
        """
        file_ids = self.add_files_to_library(library_id, [payload])
        if not file_ids:
            msg = "add_file_to_library() expected one file id"
            raise RuntimeError(msg)
        return file_ids[0]

    def add_files_to_library(self, library_id: str, payloads: list[dict]) -> list[str]:
        """Insert or update library-file documents for one library.

        Delegates the storage-native upsert, link maintenance, state bootstrap,
        and tagged-state transition to the canonical Tier 2 capability.

        Args:
            library_id: Library that owns the files.
            payloads: File documents to upsert.

        Returns:
            The ``_id`` values of the upserted file documents, in payload order.
        """
        result = self._files.upsert_files_for_library_with_state_init(
            library_id,
            payloads,
            file_states=self._file_states,
        )
        return result["file_ids"]

    def update_library_files(
        self,
        library_id: str,
        payloads: list[dict],
        *,
        remove_missing: bool,
    ) -> dict[str, int]:
        """Upsert a library's files and optionally remove files missing from the batch.

        Delegates library-scoped upsert, state initialization, remove-missing
        reconciliation, and derived cleanup to the canonical Tier 2 capability.

        Args:
            library_id: Library that owns the files.
            payloads: File documents to upsert.
            remove_missing: Whether to delete linked files omitted from this update.

        Returns:
            A count mapping with ``added``, ``updated``, and ``removed`` totals.
        """
        return self._files.reconcile_library_files(
            library_id,
            payloads,
            remove_missing=remove_missing,
            file_states=self._file_states,
            streams=self._streams,
            vectors=self._vectors,
        )

    def update_library_file_path(self, file_id: str, new_path: str) -> None:
        self._files._update_file(file_id, {"path": new_path})

    def update_library_file_scan_metadata(
        self,
        file_id: str,
        *,
        file_size: int,
        modified_time: int,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        """Patch a file document with scan metadata and mark it valid for the current scan.

        Args:
            file_id: File document ``_id``.
            file_size: File size recorded during scanning.
            modified_time: File modification time recorded during scanning.
            artist: Scan-time artist value, if available.
            album: Scan-time album value, if available.
            title: Scan-time title value, if available.
            duration_seconds: Scan-time duration value, if available.
            normalized_path: Normalized path to store when one was computed.
        """
        fields: dict[str, Any] = {
            "file_size": file_size,
            "modified_time": modified_time,
            "is_valid": 1,
            "artist": artist,
            "album": album,
            "title": title,
            "duration_seconds": duration_seconds,
            "scanned_at": now_ms().value,
        }
        if normalized_path is not None:
            fields["normalized_path"] = normalized_path
        self._files._update_file(file_id, fields)

    def update_library_file_modified_time(self, file_id: str, modified_time_ms: int) -> None:
        self._files._update_file(file_id, {"modified_time": modified_time_ms})

    def update_library_file_metadata_cache(
        self,
        file_id: str,
        *,
        artist: str | None,
        artists: list[str] | None,
        album: str | None,
        labels: list[str] | None,
        genres: list[str] | None,
        year: int | None,
    ) -> None:
        """Update the cached audio metadata fields stored on a library file document."""
        self._files._update_file(
            file_id,
            {
                "artist": artist,
                "artists": artists,
                "album": album,
                "labels": labels,
                "genres": genres,
                "year": year,
            },
        )

    def set_library_file_chromaprint(self, file_id: str, chromaprint: str) -> None:
        self._files._update_file(file_id, {"chromaprint": chromaprint})

    def update_library_file_last_tagged_at(self, file_id: str, tagged_at_ms: int) -> None:
        self._files._update_file(file_id, {"last_tagged_at": tagged_at_ms})

    def remove_file(self, file_id: str) -> None:
        """Remove one file after cleaning up its derived streams and vectors.

        Args:
            file_id: File document ID to remove.
        """
        self._files.remove_files_with_derived_cleanup(
            [file_id],
            streams=self._streams,
            vectors=self._vectors,
        )

    def remove_file_by_path(self, path: str, library_id: str | None = None) -> None:
        """Remove a file by path if a matching file document can be resolved.

        Resolves the path first, scoped to ``library_id`` when provided or across
        all libraries otherwise, then delegates to ``remove_file``. Returns
        silently when no matching file exists.
        """
        file_doc = (
            self.get_file_by_path(path, library_id)
            if library_id is not None
            else self.find_file_by_path_any_library(path)
        )
        if file_doc is None:
            return
        file_id = file_doc.get("_id")
        if not isinstance(file_id, str):
            msg = "Resolved file document must include a string '_id'"
            raise RuntimeError(msg)
        self.remove_file(file_id)

    def replace_file_tags(self, file_id: str, tags: list[dict]) -> None:
        """Replace all tag associations for a file."""
        self._tags.replace_file_tags(file_id, tags)

    def replace_tag_references(self, source_tag_id: str, target_tag_id: str) -> None:
        """Remap song→tag edges from one tag to another across all affected files."""
        self._tags.replace_tag_references(source_tag_id, target_tag_id)

    def replace_selected_tag_references(
        self,
        file_ids: list[str],
        source_tag_id: str,
        target_tag_id: str,
    ) -> None:
        """Remap song→tag edges for a selected set of files."""
        self._tags.replace_tag_references(
            source_tag_id,
            target_tag_id,
            file_ids=file_ids,
        )

    def remove_file_tags(self, file_id: str, tag_keys: list[str] | None = None) -> None:
        """Remove tag edges for one file and clean up orphaned tags."""
        self._tags.remove_file_tags(file_id, tag_keys)

    def add_library_folder(self, library_id: str, payload: dict) -> str:
        """Create a folder and link it to a library."""
        return self._files.add_library_folder(library_id, payload)

    def remove_library_folder(self, library_id: str, folder_id: str) -> None:
        """Remove a folder link from a library and delete the folder."""
        self._files.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library_id: str, payloads: list[dict]) -> None:
        """Replace all folders linked to a library."""
        self._files.replace_library_folders(library_id, payloads)

    def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        return self._files.list_existing_file_paths(paths)

    def list_library_files_for_folder(
        self,
        library_id: str,
        folder_rel_path: str,
    ) -> list[dict]:
        return self._files.list_library_files_for_folder(library_id, folder_rel_path)

    # ------------------------------------------------------------------
    # Temporary compatibility shims. Do not add new callers.
    # Parts B/E normalize, internalize, or delete these names.
    # ------------------------------------------------------------------

    def count_library_file_links(self, library_id: str) -> int:
        return self._files.count_library_file_links(library_id)

    def search_files_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None,
    ) -> list[dict]:
        return self._tags.search_files_by_tag_pattern(tag_name, pattern, limit=limit)

    def find_or_create_tag(self, name: str, value: Any) -> str:
        return self._tags._find_or_create_tag(name, value)

    def get_song_tag_edges_for_tags(
        self,
        tag_ids: list[str],
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._tags._get_song_tag_edges_for_tags(tag_ids, limit=limit)

    def update_file(self, file_id: str, fields: dict) -> None:
        """Update arbitrary fields on one library-file document."""
        self._files._update_file(file_id, fields)

    def count_songs_for_tag(self, tag_id: str) -> int:
        """Count songs that are assigned to the given tag."""
        return self._tags._count_song_tag_edges(tag_id)

    def count_file_states(self, file_id: str, state_tag_id: str) -> int:
        """Count how many times a file is assigned the given state."""
        return self._tags.count_song_tag_edges_for_file_state(file_id, state_tag_id)

    def clear_song_tags(self) -> None:
        """Remove all tag assignments from all songs."""
        return self.maintenance.truncate_song_tag_edges()

    def clear_file_links(self) -> None:
        """Remove all library-file membership records."""
        return self.maintenance.truncate_file_links()

    def clear_folder_links(self) -> None:
        """Remove all library-folder membership records."""
        return self.maintenance.truncate_folder_links()

    def clear_tags(self) -> None:
        """Remove all tag documents."""
        return self.maintenance.truncate_tags()

    def clear_files(self) -> None:
        """Remove all library-file documents."""
        return self.maintenance.truncate_files()

    def clear_folders(self) -> None:
        """Remove all library-folder documents."""
        return self.maintenance.truncate_folders()
