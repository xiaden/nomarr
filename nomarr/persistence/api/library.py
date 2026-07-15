from __future__ import annotations

from typing import Any

from nomarr.helpers.dto.repo_dto import LibraryFileRow, LibraryFolderRow, LibraryRow, LibraryScanRow, TagRow
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.database.file_repo import FileRepository
from nomarr.persistence.database.file_state_repo import FileStateRepository
from nomarr.persistence.database.file_tag_repo import FileTagRepository
from nomarr.persistence.database.folder_repo import FolderRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.scan_repo import ScanRepository
from nomarr.persistence.database.tag_repo import TagRepository


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
        file_repo: FileRepository,
        tag_repo: TagRepository,
        file_tag_repo: FileTagRepository,
        folder_repo: FolderRepository,
        scan_repo: ScanRepository,
    ) -> None:
        self._file_repo = file_repo
        self._tag_repo = tag_repo
        self._file_tag_repo = file_tag_repo
        self._folder_repo = folder_repo
        self._scan_repo = scan_repo

    async def list_orphaned_file_ids(self) -> list[int]:
        """List file IDs that have no matching library-file row."""
        return await self._file_repo.list_orphaned_file_ids()

    async def list_orphaned_tag_ids(self) -> list[int]:
        """List tag IDs that have no matching file assignment."""
        return await self._tag_repo.get_orphaned_tag_ids()

    async def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        """Delete tags by their IDs.

        Returns:
            The number of tags deleted.

        """
        return await self._tag_repo.delete_tags_by_ids(tag_ids)

    async def truncate_files(self) -> None:
        """Remove all library-file rows."""
        return await self._file_repo.truncate_files()

    async def truncate_file_links(self) -> None:
        """Remove all library-file membership records."""
        return await self._file_repo.truncate_file_links()

    async def truncate_folder_links(self) -> None:
        """Remove all library-folder membership records."""
        return await self._folder_repo.truncate_folder_links()

    async def truncate_folders(self) -> None:
        """Remove all library-folder rows."""
        return await self._folder_repo.truncate_folders()

    async def truncate_tags(self) -> None:
        """Remove all tag rows."""
        return await self._tag_repo.truncate_tags()

    async def truncate_song_tag_edges(self) -> None:
        """Remove all file-to-tag assignment edges."""
        return await self._file_tag_repo.truncate_file_tag_assignments()

    async def truncate_scan_records(self) -> None:
        """Remove all scan records."""
        return await self._scan_repo.truncate_scans()


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
        library_repo: LibraryRepository,
        file_repo: FileRepository,
        folder_repo: FolderRepository,
        scan_repo: ScanRepository,
        tag_repo: TagRepository,
        file_tag_repo: FileTagRepository,
        file_state_repo: FileStateRepository,
    ) -> None:
        self._library_repo = library_repo
        self._file_repo = file_repo
        self._folder_repo = folder_repo
        self._scan_repo = scan_repo
        self._tag_repo = tag_repo
        self._file_tag_repo = file_tag_repo
        self._file_state_repo = file_state_repo
        self.maintenance: LibraryMaintenanceDb = LibraryMaintenanceDb(
            file_repo=file_repo,
            tag_repo=tag_repo,
            file_tag_repo=file_tag_repo,
            folder_repo=folder_repo,
            scan_repo=scan_repo,
        )

    # ------------------------------------------------------------------
    # Public repo accessors — used by callers that previously went through
    # the temporary compatibility shims.
    # ------------------------------------------------------------------

    @property
    def file_repo(self) -> FileRepository:
        """Public accessor for the file repository."""
        return self._file_repo

    @property
    def tag_repo(self) -> TagRepository:
        """Public accessor for the tag repository."""
        return self._tag_repo

    @property
    def file_tag_repo(self) -> FileTagRepository:
        """Public accessor for the file-tag repository."""
        return self._file_tag_repo

    @property
    def file_state_repo(self) -> FileStateRepository:
        """Public accessor for the file-state repository."""
        return self._file_state_repo

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    async def add_library(self, payload: dict[str, Any]) -> int:
        """Create a new library and return its ID."""
        return await self._library_repo.add_library(payload)

    async def get_library(self, library_id: int) -> LibraryRow | None:
        """Get a library by its ID."""
        return await self._library_repo.get_library(library_id)

    async def get_library_by_name(self, name: str) -> LibraryRow | None:
        """Get a library by its name."""
        return await self._library_repo.get_library_by_name(name)

    async def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        """List all libraries, optionally filtering to enabled only."""
        return await self._library_repo.list_libraries(enabled_only=enabled_only)

    async def list_library_keys(self) -> list[int]:
        """Return the IDs of all libraries."""
        return await self._library_repo.list_library_keys()

    async def update_library(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update fields on a library."""
        await self._library_repo.update_library(library_id, fields)

    async def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library."""
        return await self._library_repo.get_pipeline_state(library_id)

    async def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return library IDs where the given axis field matches the value."""
        return await self._library_repo.get_libraries_in_axis_state(axis_field, axis_value)

    async def update_pipeline_axis(self, library_id: int, axis_field: str, axis_value: str) -> None:
        """Update a single pipeline axis field on a library row."""
        await self._library_repo.update_pipeline_axis(library_id, axis_field, axis_value)

    async def get_file(self, file_id: int) -> LibraryFileRow | None:
        """Get a library file by its ID."""
        return await self._file_repo.get_file(file_id)

    async def get_file_by_path(self, path: str, library_id: int) -> LibraryFileRow | None:
        """Get a library file by path within a specific library."""
        return await self._file_repo.get_file_by_path(path, library_id)

    async def find_file_by_path_any_library(self, path: str) -> LibraryFileRow | None:
        """Get a library file by path across all libraries."""
        return await self._file_repo.get_file_by_path_unscoped(path)

    async def list_files_by_ids(self, file_ids: list[int]) -> list[LibraryFileRow]:
        """Return library file rows for the given file IDs."""
        return await self._file_repo.get_files_by_ids(file_ids)

    async def list_files(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return library file rows matching the optional filters and limit."""
        return await self._file_repo.list_files(filters=filters, limit=limit)

    async def count_files(self) -> int:
        """Return the total number of library-file rows."""
        return await self._file_repo.count_files()

    async def get_library_ids_for_files(self, file_ids: list[int]) -> dict[int, int]:
        """Return mapping of file_id → library_id for the given file IDs."""
        return await self._file_repo.get_library_ids_for_files(file_ids)

    async def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count files tagged since the given cutoff timestamp (epoch ms)."""
        return await self._file_repo.count_recently_tagged(cutoff_ms)

    async def list_library_file_ids(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[int]:
        """Return file IDs belonging to a library, with optional limit."""
        return await self._file_repo.list_library_file_ids(library_id, limit=limit)

    async def list_library_files(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return file rows belonging to a library, with optional limit."""
        return await self._file_repo.list_library_files(library_id, limit=limit)

    async def find_library_file_by_chromaprint(
        self,
        library_id: int,
        chromaprint: str,
    ) -> LibraryFileRow | None:
        """Find a library file by its Chromaprint fingerprint."""
        return await self._file_repo.find_by_chromaprint(library_id, chromaprint)

    async def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count files that have a tag with the given key and value."""
        return await self._file_tag_repo.count_files_by_tag(tag_key, target_value)

    async def search_files_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[LibraryFileRow]:
        """Search for files with an exact tag key/value match."""
        return await self._file_tag_repo.search_files_by_tag(tag_key, value, limit=limit)

    async def search_files_by_tag_contains(
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
        return await self._file_tag_repo.search_files_by_tag_contains(tag_key, value, limit=limit)

    async def list_file_ids_for_tag_id(self, tag_id: int, *, limit: int | None, offset: int = 0) -> list[int]:
        """Return file IDs assigned to a tag, with paging."""
        return await self._file_tag_repo.list_file_ids_for_tag(tag_id, limit=limit, offset=offset)

    async def get_tag(self, tag_id: int) -> TagRow | None:
        """Get a tag by its ID."""
        return await self._tag_repo.get_tag(tag_id)

    async def list_tags_for_file(self, file_id: int) -> list[TagRow]:
        """Return all tags assigned to a file."""
        return await self._file_tag_repo.get_tags_for_file(file_id)

    async def list_all_tag_names(self, limit: int) -> list[str]:
        """Return distinct tag names, up to the given limit."""
        return await self._tag_repo.list_all_tag_names(limit=limit)

    async def list_tags(
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
        return await self._tag_repo.list_tags(name=name, value=value, limit=limit, offset=offset)

    async def count_tags(self) -> int:
        """Return the total number of tag rows."""
        return await self._tag_repo.count_tags()

    async def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count tags matching name/search filters."""
        return await self._tag_repo.count_tags_filtered(name=name, search=search)

    async def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List tags with pre-computed song counts in a single query."""
        return await self._tag_repo.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    async def list_tags_by_name(self, name: str, limit: int) -> list[TagRow]:
        """Return tags matching an exact name, up to the given limit."""
        return await self._tag_repo.list_tags(name=name, limit=limit)

    async def list_genre_tags_for_files(self, file_ids: list[int]) -> list[TagRow]:
        """Return genre tags assigned to any of the given files."""
        return await self._file_tag_repo.get_genre_tags_for_files(file_ids)

    async def list_file_tags_for_files(
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
        rows = await self._file_tag_repo.get_tags_for_files_batch(
            file_ids,
            name_starts_with=name_starts_with,
            include_edge=False,
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

    async def get_folder(self, folder_id: int) -> LibraryFolderRow | None:
        """Get a library folder by its ID."""
        return await self._folder_repo.get_folder(folder_id)

    async def list_folders_for_library(self, library_id: int) -> list[LibraryFolderRow]:
        """Return all folders linked to a library."""
        return await self._folder_repo.list_folders_for_library(library_id)

    async def list_tracks_for_matching(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return file rows suitable for track matching, with optional limit."""
        return await self._file_repo.list_tracks_for_matching(library_id, limit=limit)

    async def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        """Return value frequency distributions for the given tag names."""
        return await self._tag_repo.get_tag_value_frequencies_batch(tag_names, limit=limit)

    async def remove_library(self, library_id: int) -> bool:
        """Delete a library and all associated data.

        Returns True if the library was found and deleted, False if not found.
        Delegates to the LibraryRepository cascade delete.
        Orphaned tag rows are not cleaned up — callers should invoke
        cleanup_orphaned_tags() separately if needed.
        """
        if not await self._library_repo.get_library(library_id):
            return False
        await self._library_repo.remove_library(library_id)
        return True

    async def add_file_to_library(self, library_id: int, payload: dict) -> int:
        """Insert or update one library-file row.

        Returns the ``id`` of the upserted row.

        Raises:
            RuntimeError: If the upsert returns no file IDs.

        """
        file_ids = await self._file_repo.upsert_files_for_library(library_id, [payload])
        if not file_ids:
            msg = "add_file_to_library() expected one file id"
            raise RuntimeError(msg)
        return file_ids[0]

    async def add_files_to_library(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        initial_state: str = "tagged",
    ) -> list[int]:
        """Upsert files and bootstrap initial states for newly created rows."""
        existing_paths = set(
            await self._file_repo.list_existing_file_paths([str(p["path"]) for p in payloads if "path" in p])
        )
        file_ids = await self._file_repo.upsert_files_for_library(library_id, payloads)
        # Bootstrap state only for files that were newly created
        for file_id, payload in zip(file_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                await self._file_state_repo.ensure_file_state(file_id, initial_state)
        return file_ids

    async def update_library_files(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        """Reconcile library files: upsert, init states, optionally remove missing.

        FK ON DELETE CASCADE handles derived data cleanup (streams, vectors,
        tags, state assignments) — no explicit derived-data removal needed.
        """
        result: dict[str, int] = {"added": 0, "updated": 0, "removed": 0}

        # Determine existing paths to distinguish new vs updated files
        incoming_paths = [str(p["path"]) for p in payloads if "path" in p]
        existing_paths = set(await self._file_repo.list_existing_file_paths(incoming_paths))

        # Upsert files
        file_ids = await self._file_repo.upsert_files_for_library(library_id, payloads)
        new_count = 0
        for file_id, payload in zip(file_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                new_count += 1
                await self._file_state_repo.ensure_file_state(file_id, "tagged")
        result["added"] = new_count
        result["updated"] = len(file_ids) - new_count

        if remove_missing:
            current_ids = set(await self._file_repo.list_library_file_ids(library_id))
            upserted_ids = set(file_ids)
            to_remove = sorted(current_ids - upserted_ids)
            if to_remove:
                await self._file_repo.remove_files(to_remove)
                # FK CASCADE handles file_state_assignments, file_tags, etc.
            result["removed"] = len(to_remove)

        return result

    async def update_library_file_path(self, file_id: int, new_path: str) -> None:
        """Update the path of a library file."""
        await self._file_repo.update_file(file_id, {"path": new_path})

    async def update_library_file_scan_metadata(
        self,
        file_id: int,
        *,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        """Patch a file row with scan metadata and mark it valid for the current scan.

        Args:
            file_id: File row id.
            file_size: File size recorded during scanning.
            modified_time: File modification time recorded during scanning.
            duration_seconds: Scan-time duration value, if available.
            normalized_path: Normalized path to store when one was computed.

        """
        fields: dict[str, Any] = {
            "file_size": file_size,
            "modified_time": modified_time,
            "is_valid": 1,
            "duration_seconds": duration_seconds,
            "scanned_at": now_ms().value,
        }
        if normalized_path is not None:
            fields["normalized_path"] = normalized_path
        await self._file_repo.update_file(file_id, fields)

    async def update_library_file_modified_time(self, file_id: int, modified_time_ms: int) -> None:
        """Update the modification timestamp of a library file."""
        await self._file_repo.update_file(file_id, {"modified_time": modified_time_ms})

    async def set_library_file_chromaprint(self, file_id: int, chromaprint: str) -> None:
        """Set the Chromaprint fingerprint on a library file."""
        await self._file_repo.update_file(file_id, {"chromaprint": chromaprint})

    async def update_library_file_last_tagged_at(self, file_id: int, tagged_at_ms: int) -> None:
        """Update the last-tagged timestamp on a library file."""
        await self._file_repo.update_file(file_id, {"last_tagged_at": tagged_at_ms})

    async def remove_file(self, file_id: int) -> None:
        """Remove one file. FK CASCADE handles derived streams and vectors.

        Args:
            file_id: File row id to remove.

        """
        await self._file_repo.delete_file(file_id)

    async def remove_file_by_path(self, path: str, library_id: int | None = None) -> None:
        """Remove a file by path if a matching file row can be resolved.

        Resolves the path first, scoped to ``library_id`` when provided or across
        all libraries otherwise, then delegates to ``remove_file``. Returns
        silently when no matching file exists.
        """
        file_row = (
            await self.get_file_by_path(path, library_id)
            if library_id is not None
            else await self.find_file_by_path_any_library(path)
        )
        if file_row is None:
            return
        file_id: int = file_row["id"]
        await self.remove_file(file_id)

    async def replace_file_tags(self, file_id: int, tags: list[dict]) -> None:
        """Replace all tag associations for a file."""
        await self._file_tag_repo.replace_file_tags(file_id, tags)

    async def replace_tag_references(self, source_tag_id: int, target_tag_id: int) -> None:
        """Remap song→tag edges from one tag to another across all affected files."""
        await self._file_tag_repo.replace_tag_references(source_tag_id, target_tag_id)

    async def replace_selected_tag_references(
        self,
        file_ids: list[int],
        source_tag_id: int,
        target_tag_id: int,
    ) -> None:
        """Remap song→tag edges for a selected set of files."""
        await self._file_tag_repo.replace_tag_references(
            source_tag_id,
            target_tag_id,
            file_ids=file_ids,
        )

    async def remove_file_tags(self, file_id: int, tag_keys: list[int] | None = None) -> None:
        """Remove tag edges for one file and clean up orphaned tags."""
        if tag_keys:
            for tag_id in tag_keys:
                await self._file_tag_repo.remove_tag_from_file(file_id, tag_id)
        await self._tag_repo.cleanup_orphaned_tags()

    async def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        """Create a folder and link it to a library."""
        return await self._folder_repo.add_library_folder(library_id, payload)

    async def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        """Remove a folder link from a library and delete the folder."""
        await self._folder_repo.remove_library_folder(library_id, folder_id)

    async def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        """Replace all folders linked to a library."""
        await self._folder_repo.replace_library_folders(library_id, payloads)

    async def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        """Return the subset of the given paths that already have library-file rows."""
        return await self._file_repo.list_existing_file_paths(paths)

    async def list_library_files_for_folder(
        self,
        library_id: int,
        folder_rel_path: str,
    ) -> list[LibraryFileRow]:
        """Return library files within a specific folder of a library."""
        return await self._file_repo.list_files_for_folder(library_id, folder_rel_path)

    # ------------------------------------------------------------------
    # Scan methods — delegate to ScanRepository
    # ------------------------------------------------------------------

    async def get_scan(self, library_id: int) -> LibraryScanRow | None:
        """Return the most recent scan record for a library."""
        return await self._scan_repo.get_scan_record(library_id)

    async def add_scan(self, library_id: int, payload: dict[str, Any]) -> int:
        """Create a new scan record for a library."""
        return await self._scan_repo.create_scan({**payload, "library_id": library_id})

    async def update_scan(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update an existing scan record or create one if none exists."""
        scan = await self._scan_repo.get_scan_record(library_id)
        if scan:
            await self._scan_repo.update_scan(scan["id"], fields)
        else:
            await self._scan_repo.create_scan({**fields, "library_id": library_id})

    async def remove_scan(self, library_id: int) -> None:
        """Delete the scan record for a library if one exists."""
        scan = await self._scan_repo.get_scan_record(library_id)
        if scan:
            await self._scan_repo.delete_scan_record(scan["id"])

    async def clear_scans(self) -> None:
        """Remove all scan records."""
        await self.maintenance.truncate_scan_records()
