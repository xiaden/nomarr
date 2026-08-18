"""Song and folder sub-facade for the library persistence surface.

Holds all song-domain (``songs`` table) and folder-domain
(``library_folders`` table) intent methods. Wired into ``LibraryDb`` as
its ``songs`` namespace (namespaced-forwarding split per
DD-persistence-intent-facade-rebuild §Phase 1). Methods were extracted
verbatim from the former single ``LibraryDb`` when the sealed library
facade was split into sub-facades — including the former maintenance
surface — signatures and behavior unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import LibraryFolderRow, SongRow
    from nomarr.persistence.database.folder_repo import FolderRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class LibrarySongsDb:
    """Persistence sub-facade for library song and folder operations.

    Domain identity: ``path`` (absolute file path). Song rows are keyed
    by their integer primary key internally; callers address songs by
    path where the intent method allows it.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        song_repo: SongRepository,
        folder_repo: FolderRepository,
        song_state_repo: SongStateRepository,
    ) -> None:
        self._session = session
        self._song_repo = song_repo
        self._folder_repo = folder_repo
        self._song_state_repo = song_state_repo

    # ------------------------------------------------------------------
    # Song lookups
    # ------------------------------------------------------------------

    def get_song(self, song_id: int) -> SongRow | None:
        """Get a library song by its ID."""
        return self._song_repo.get_song(song_id)

    def get_song_by_path(self, path: str, library_id: int) -> SongRow | None:
        """Get a library song by path within a specific library."""
        return self._song_repo.get_song_by_path(path, library_id)

    def find_song_by_path_any_library(self, path: str) -> SongRow | None:
        """Get a library song by path across all libraries."""
        return self._song_repo.get_song_by_path_unscoped(path)

    def list_songs_by_ids(self, song_ids: list[int]) -> list[SongRow]:
        """Return library song rows for the given song IDs."""
        return self._song_repo.get_songs_by_ids(song_ids)

    def get_library_ids_for_songs(self, song_ids: list[int]) -> dict[int, int]:
        """Return mapping of song_id → library_id for the given song IDs."""
        return self._song_repo.get_library_ids_for_songs(song_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count songs tagged since the given cutoff timestamp (epoch ms)."""
        return self._song_repo.count_recently_tagged(cutoff_ms)

    def list_library_song_ids(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[int]:
        """Return song IDs belonging to a library, with optional limit."""
        return self._song_repo.list_library_song_ids(library_id, limit=limit)

    def list_songs(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return song rows belonging to a library, with optional limit."""
        return self._song_repo.list_songs(library_id, limit=limit)

    def count_songs(self, library_id: int) -> int:
        """Count songs in a library."""
        return self._song_repo.count_songs(library_id)

    def count_songs_for_library(self, library_id: int) -> int:
        """Return the number of songs belonging to a library."""
        return self._song_repo.count_songs(library_id)

    def find_library_song_by_chromaprint(
        self,
        library_id: int,
        chromaprint: str,
    ) -> SongRow | None:
        """Find a library song by its Chromaprint fingerprint."""
        return self._song_repo.find_song_by_chromaprint(library_id, chromaprint)

    # ------------------------------------------------------------------
    # Song mutations
    # ------------------------------------------------------------------

    def add_song_to_library(self, library_id: int, payload: dict) -> int:
        """Insert or update one library-song row.

        Returns the ``id`` of the upserted row.

        Raises:
            RuntimeError: If the upsert returns no song IDs.

        """
        song_ids = self._song_repo.upsert_songs_for_library(library_id, [payload])
        if not song_ids:
            msg = "add_song_to_library() expected one song id"
            raise RuntimeError(msg)
        return song_ids[0]

    def add_songs_to_library(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        initial_state: str = "tagged",
    ) -> list[int]:
        """Upsert songs and bootstrap initial states for newly created rows."""
        existing_paths = set(
            self._song_repo.list_existing_song_paths([str(p["path"]) for p in payloads if "path" in p])
        )
        song_ids = self._song_repo.upsert_songs_for_library(library_id, payloads)
        # Bootstrap state only for songs that were newly created
        for song_id, payload in zip(song_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                self._song_state_repo.ensure_song_state(song_id, initial_state)
        return song_ids

    def update_songs(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        """Reconcile library songs: upsert, init states, optionally remove missing.

        FK ON DELETE CASCADE handles derived data cleanup (streams, vectors,
        tags, state assignments) — no explicit derived-data removal needed.
        """
        allowed_fields = {
            "path",
            "normalized_path",
            "folder_id",
            "file_size",
            "modified_time",
            "duration_seconds",
            "scanned_at",
        }
        invalid_fields = sorted({key for payload in payloads for key in payload if key not in allowed_fields})
        if invalid_fields:
            raise ValueError(
                "update_songs() accepts scan/reconciliation fields only; "
                f"use an intent method for: {', '.join(invalid_fields)}"
            )
        result: dict[str, int] = {"added": 0, "updated": 0, "removed": 0}

        # Determine existing paths to distinguish new vs updated songs
        incoming_paths = [str(p["path"]) for p in payloads if "path" in p]
        existing_paths = set(self._song_repo.list_existing_song_paths(incoming_paths))

        # Upsert songs
        song_ids = self._song_repo.upsert_songs_for_library(library_id, payloads)
        new_count = 0
        for song_id, payload in zip(song_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                new_count += 1
                self._song_state_repo.ensure_song_state(song_id, "tagged")
        result["added"] = new_count
        result["updated"] = len(song_ids) - new_count

        if remove_missing:
            current_ids = set(self._song_repo.list_library_song_ids(library_id))
            upserted_ids = set(song_ids)
            to_remove = sorted(current_ids - upserted_ids)
            if to_remove:
                self._song_repo.remove_songs(to_remove)
                # FK CASCADE handles song_state_assignments, song_tags, etc.
            result["removed"] = len(to_remove)

        return result

    def update_library_song_path(self, song_id: int, new_path: str) -> None:
        """Update the path of a library song."""
        self._song_repo.update_song(song_id, {"path": new_path})

    def update_library_song_scan_metadata(
        self,
        song_id: int,
        *,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        """Patch a song row with scan metadata and mark it valid for the current scan.

        Args:
            song_id: Song row id.
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
        self._song_repo.update_song(song_id, fields)

    def update_library_song_modified_time(self, song_id: int, modified_time_ms: int) -> None:
        """Update the modification timestamp of a library song."""
        self._song_repo.update_song(song_id, {"modified_time": modified_time_ms})

    def set_library_song_chromaprint(self, song_id: int, chromaprint: str) -> None:
        """Set the Chromaprint fingerprint on a library song."""
        self._song_repo.update_song(song_id, {"chromaprint": chromaprint})

    def update_library_song_last_tagged_at(self, song_id: int, tagged_at_ms: int) -> None:
        """Update the last-tagged timestamp on a library song."""
        self._song_repo.update_song(song_id, {"last_tagged_at": tagged_at_ms})

    def remove_song(self, song_id: int) -> None:
        """Remove one song. FK CASCADE handles derived streams and vectors.

        Args:
            song_id: Song row id to remove.

        """
        self._song_repo.delete_song(song_id)

    def remove_song_by_path(self, path: str, library_id: int | None = None) -> None:
        """Remove a song by path if a matching song row can be resolved.

        Resolves the path first, scoped to ``library_id`` when provided or across
        all libraries otherwise, then delegates to ``remove_song``. Returns
        silently when no matching song exists.
        """
        song_row = (
            self.get_song_by_path(path, library_id)
            if library_id is not None
            else self.find_song_by_path_any_library(path)
        )
        if song_row is None:
            return
        song_id: int = song_row["id"]
        self.remove_song(song_id)

    def list_existing_song_paths(self, paths: list[str]) -> list[str]:
        """Return the subset of the given paths that already have library-song rows."""
        return self._song_repo.list_existing_song_paths(paths)

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
        return self._folder_repo.add_library_folder(library_id, payload)

    def replace_library_folder(self, library_id: int, folder_id: int, payload: dict[str, Any]) -> None:
        """Atomically replace one folder linked to a library."""
        self._folder_repo.replace_library_folder(library_id, folder_id, payload)

    def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        """Remove a folder link from a library and delete the folder."""
        self._folder_repo.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        """Replace all folders linked to a library."""
        self._folder_repo.replace_library_folders(library_id, payloads)

    def list_songs_for_folder(
        self,
        library_id: int,
        folder_rel_path: str,
    ) -> list[SongRow]:
        """Return library songs within a specific folder of a library."""
        return self._song_repo.list_songs_for_folder(library_id, folder_rel_path)

    # ------------------------------------------------------------------
    # Track matching and maintenance
    # ------------------------------------------------------------------

    def list_tracks_for_matching(
        self,
        library_id: int,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return song rows suitable for track matching, with optional limit."""
        return self._song_repo.list_tracks_for_matching(library_id, limit=limit)

    def list_orphaned_song_ids(self) -> list[int]:
        """List song IDs that have no matching library-song row."""
        return self._song_repo.list_orphaned_song_ids()

    def truncate_songs(self) -> None:
        """Remove all library-song rows."""
        return self._song_repo.truncate_songs()

    def truncate_song_links(self) -> None:
        """Remove all library-song membership records."""
        return self._song_repo.truncate_song_links()

    def truncate_folder_links(self) -> None:
        """Remove all library-folder membership records."""
        return self._folder_repo.truncate_folder_links()

    def truncate_folders(self) -> None:
        """Remove all library-folder rows."""
        return self._folder_repo.truncate_folders()
