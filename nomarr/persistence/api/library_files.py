"""File and folder sub-facade for the library persistence surface.

Holds all file-domain (``songs`` table) and folder-domain
(``library_folders`` table) intent methods. Wired into ``LibraryDb`` as
its ``files`` namespace (namespaced-forwarding split per
DD-persistence-intent-facade-rebuild §Phase 1). Methods moved verbatim
from ``LibraryDb`` — including the former maintenance surface —
signatures and behavior unchanged.

READ/WRITE classification (AR-2): READ methods use SQLAlchemy autobegin
and need no transaction context; WRITE methods (inserts/updates/deletes/
upserts/truncates) must be called inside ``LibraryDb.transaction()`` and
raise :class:`FacadeMisuseError` otherwise.

READ:   get_file, get_file_by_path, find_file_by_path_any_library,
        list_files_by_ids, list_files, count_files, get_library_ids_for_files,
        count_recently_tagged, list_library_file_ids, list_songs,
        count_files_for_library, find_library_file_by_chromaprint,
        list_existing_file_paths, get_folder, list_folders_for_library,
        list_songs_for_folder, list_tracks_for_matching, list_orphaned_file_ids
WRITE:  add_file_to_library, add_files_to_library, update_songs,
        update_library_file_path, update_library_file_scan_metadata,
        update_library_file_modified_time, set_library_file_chromaprint,
        update_library_file_last_tagged_at, update_file_fields, remove_file,
        remove_file_by_path, add_library_folder, remove_library_folder,
        replace_library_folders, truncate_files, truncate_file_links,
        truncate_folder_links, truncate_folders
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.exceptions import FacadeMisuseError
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import LibraryFileRow, LibraryFolderRow
    from nomarr.persistence.database.file_repo import FileRepository
    from nomarr.persistence.database.file_state_repo import FileStateRepository
    from nomarr.persistence.database.folder_repo import FolderRepository


class LibraryFilesDb:
    """Persistence sub-facade for library file and folder operations.

    Domain identity: ``path`` (absolute file path). File rows are keyed
    by their integer primary key internally; callers address files by
    path where the intent method allows it.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        file_repo: FileRepository,
        folder_repo: FolderRepository,
        file_state_repo: FileStateRepository,
    ) -> None:
        self._session = session
        self._file_repo = file_repo
        self._folder_repo = folder_repo
        self._file_state_repo = file_state_repo

    def _require_transaction(self, method_name: str) -> None:
        """Raise :class:`FacadeMisuseError` when no transaction is active (AR-2)."""
        if not cast("Session", self._session).in_transaction():
            raise FacadeMisuseError(
                f"{type(self).__name__}.{method_name}() is a write method — call within a transaction() context"
            )

    # ------------------------------------------------------------------
    # File lookups
    # ------------------------------------------------------------------

    def get_file(self, file_id: int) -> LibraryFileRow | None:
        """Get a library file by its ID."""
        return self._file_repo.get_file(file_id)

    def get_file_by_path(self, path: str, library_id: int) -> LibraryFileRow | None:
        """Get a library file by path within a specific library."""
        return self._file_repo.get_file_by_path(path, library_id)

    def find_file_by_path_any_library(self, path: str) -> LibraryFileRow | None:
        """Get a library file by path across all libraries."""
        return self._file_repo.get_file_by_path_unscoped(path)

    def list_files_by_ids(self, file_ids: list[int]) -> list[LibraryFileRow]:
        """Return library file rows for the given file IDs."""
        return self._file_repo.get_files_by_ids(file_ids)

    def list_files(
        self,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return library file rows matching the optional filters and limit."""
        return self._file_repo.list_files(filters=filters, limit=limit)

    def count_files(self) -> int:
        """Return the total number of library-file rows."""
        return self._file_repo.count_files()

    def get_library_ids_for_files(self, file_ids: list[int]) -> dict[int, int]:
        """Return mapping of file_id → library_id for the given file IDs."""
        return self._file_repo.get_library_ids_for_files(file_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count files tagged since the given cutoff timestamp (epoch ms)."""
        return self._file_repo.count_recently_tagged(cutoff_ms)

    def list_library_file_ids(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[int]:
        """Return file IDs belonging to a library, with optional limit."""
        return self._file_repo.list_library_file_ids(library_id, limit=limit)

    def list_songs(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return file rows belonging to a library, with optional limit."""
        return self._file_repo.list_songs(library_id, limit=limit)

    def count_files_for_library(self, library_id: int) -> int:
        """Return the number of files belonging to a library."""
        return self._file_repo.count_songs(library_id)

    def find_library_file_by_chromaprint(
        self,
        library_id: int,
        chromaprint: str,
    ) -> LibraryFileRow | None:
        """Find a library file by its Chromaprint fingerprint."""
        return self._file_repo.find_by_chromaprint(library_id, chromaprint)

    # ------------------------------------------------------------------
    # File mutations
    # ------------------------------------------------------------------

    def add_file_to_library(self, library_id: int, payload: dict) -> int:
        """Insert or update one library-file row.

        Returns the ``id`` of the upserted row.

        Raises:
            RuntimeError: If the upsert returns no file IDs.

        """
        self._require_transaction("add_file_to_library")
        file_ids = self._file_repo.upsert_files_for_library(library_id, [payload])
        if not file_ids:
            msg = "add_file_to_library() expected one file id"
            raise RuntimeError(msg)
        return file_ids[0]

    def add_files_to_library(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        initial_state: str = "tagged",
    ) -> list[int]:
        """Upsert files and bootstrap initial states for newly created rows."""
        self._require_transaction("add_files_to_library")
        existing_paths = set(
            self._file_repo.list_existing_file_paths([str(p["path"]) for p in payloads if "path" in p])
        )
        file_ids = self._file_repo.upsert_files_for_library(library_id, payloads)
        # Bootstrap state only for files that were newly created
        for file_id, payload in zip(file_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                self._file_state_repo.ensure_file_state(file_id, initial_state)
        return file_ids

    def update_songs(
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
        self._require_transaction("update_songs")
        result: dict[str, int] = {"added": 0, "updated": 0, "removed": 0}

        # Determine existing paths to distinguish new vs updated files
        incoming_paths = [str(p["path"]) for p in payloads if "path" in p]
        existing_paths = set(self._file_repo.list_existing_file_paths(incoming_paths))

        # Upsert files
        file_ids = self._file_repo.upsert_files_for_library(library_id, payloads)
        new_count = 0
        for file_id, payload in zip(file_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                new_count += 1
                self._file_state_repo.ensure_file_state(file_id, "tagged")
        result["added"] = new_count
        result["updated"] = len(file_ids) - new_count

        if remove_missing:
            current_ids = set(self._file_repo.list_library_file_ids(library_id))
            upserted_ids = set(file_ids)
            to_remove = sorted(current_ids - upserted_ids)
            if to_remove:
                self._file_repo.remove_files(to_remove)
                # FK CASCADE handles file_state_assignments, file_tags, etc.
            result["removed"] = len(to_remove)

        return result

    def update_library_file_path(self, file_id: int, new_path: str) -> None:
        """Update the path of a library file."""
        self._require_transaction("update_library_file_path")
        self._file_repo.update_file(file_id, {"path": new_path})

    def update_library_file_scan_metadata(
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
        self._require_transaction("update_library_file_scan_metadata")
        fields: dict[str, Any] = {
            "file_size": file_size,
            "modified_time": modified_time,
            "is_valid": 1,
            "duration_seconds": duration_seconds,
            "scanned_at": now_ms().value,
        }
        if normalized_path is not None:
            fields["normalized_path"] = normalized_path
        self._file_repo.update_file(file_id, fields)

    def update_library_file_modified_time(self, file_id: int, modified_time_ms: int) -> None:
        """Update the modification timestamp of a library file."""
        self._require_transaction("update_library_file_modified_time")
        self._file_repo.update_file(file_id, {"modified_time": modified_time_ms})

    def set_library_file_chromaprint(self, file_id: int, chromaprint: str) -> None:
        """Set the Chromaprint fingerprint on a library file."""
        self._require_transaction("set_library_file_chromaprint")
        self._file_repo.update_file(file_id, {"chromaprint": chromaprint})

    def update_library_file_last_tagged_at(self, file_id: int, tagged_at_ms: int) -> None:
        """Update the last-tagged timestamp on a library file."""
        self._require_transaction("update_library_file_last_tagged_at")
        self._file_repo.update_file(file_id, {"last_tagged_at": tagged_at_ms})

    def update_file_fields(self, file_id: int, fields: dict[str, Any]) -> None:
        """Update arbitrary fields on a library file row.

        Generic field-update facade for callers that need to patch one or
        more columns on a file row without going through a specialised
        setter.

        Args:
            file_id: Primary key of the file row to update.
            fields: Mapping of column names to their new values.

        """
        self._require_transaction("update_file_fields")
        self._file_repo.update_file(file_id, fields)

    def remove_file(self, file_id: int) -> None:
        """Remove one file. FK CASCADE handles derived streams and vectors.

        Args:
            file_id: File row id to remove.

        """
        self._require_transaction("remove_file")
        self._file_repo.delete_file(file_id)

    def remove_file_by_path(self, path: str, library_id: int | None = None) -> None:
        """Remove a file by path if a matching file row can be resolved.

        Resolves the path first, scoped to ``library_id`` when provided or across
        all libraries otherwise, then delegates to ``remove_file``. Returns
        silently when no matching file exists.
        """
        self._require_transaction("remove_file_by_path")
        file_row = (
            self.get_file_by_path(path, library_id)
            if library_id is not None
            else self.find_file_by_path_any_library(path)
        )
        if file_row is None:
            return
        file_id: int = file_row["id"]
        self.remove_file(file_id)

    def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        """Return the subset of the given paths that already have library-file rows."""
        return self._file_repo.list_existing_file_paths(paths)

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def get_folder(self, folder_id: int) -> LibraryFolderRow | None:
        """Get a library folder by its ID."""
        return self._folder_repo.get_folder(folder_id)

    def list_folders_for_library(self, library_id: int) -> list[LibraryFolderRow]:
        """Return all folders linked to a library."""
        return self._folder_repo.list_folders_for_library(library_id)

    def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        """Create a folder and link it to a library."""
        self._require_transaction("add_library_folder")
        return self._folder_repo.add_library_folder(library_id, payload)

    def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        """Remove a folder link from a library and delete the folder."""
        self._require_transaction("remove_library_folder")
        self._folder_repo.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        """Replace all folders linked to a library."""
        self._require_transaction("replace_library_folders")
        self._folder_repo.replace_library_folders(library_id, payloads)

    def list_songs_for_folder(
        self,
        library_id: int,
        folder_rel_path: str,
    ) -> list[LibraryFileRow]:
        """Return library files within a specific folder of a library."""
        return self._file_repo.list_files_for_folder(library_id, folder_rel_path)

    # ------------------------------------------------------------------
    # Track matching and maintenance
    # ------------------------------------------------------------------

    def list_tracks_for_matching(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        """Return file rows suitable for track matching, with optional limit."""
        return self._file_repo.list_tracks_for_matching(library_id, limit=limit)

    def list_orphaned_file_ids(self) -> list[int]:
        """List file IDs that have no matching library-file row."""
        return self._file_repo.list_orphaned_file_ids()

    def truncate_files(self) -> None:
        """Remove all library-file rows."""
        self._require_transaction("truncate_files")
        return self._file_repo.truncate_files()

    def truncate_file_links(self) -> None:
        """Remove all library-file membership records."""
        self._require_transaction("truncate_file_links")
        return self._file_repo.truncate_file_links()

    def truncate_folder_links(self) -> None:
        """Remove all library-folder membership records."""
        self._require_transaction("truncate_folder_links")
        return self._folder_repo.truncate_folder_links()

    def truncate_folders(self) -> None:
        """Remove all library-folder rows."""
        self._require_transaction("truncate_folders")
        return self._folder_repo.truncate_folders()
