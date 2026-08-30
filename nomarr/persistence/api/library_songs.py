"""Song and folder sub-facade for the library persistence surface.

Holds all song-domain (``songs`` table) and folder-domain
(``library_folders`` table) intent methods. Wired into ``LibraryDb`` as
its ``songs`` namespace (namespaced-forwarding split per
DD-persistence-intent-facade-rebuild §Phase 1).

Overlap: a concurrent song-domain agent (TASK-song-intent-facade-correction-A)
is mid-refactor of this file (Song value mapping, state-intent initialization,
hydration). This change (P3-S3/P3-S5 of TASK-library-domain-facades-A) only
changes library *scoping*: library-scoped methods accept the domain ``Library``
natural key and resolve the storage ``library_id`` internally, and folder-facing
methods use the ``LibraryFolder`` value object with relative-path identity. It
does not redesign song values/facades or hydration — that remains the song
plan's ownership. Concurrent hunks are preserved verbatim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryFolder
    from nomarr.helpers.dto.hydration_dto import HydrateSongInput
    from nomarr.persistence.database.folder_repo import FolderRepository
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_hydration_repo import SongHydrationRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class LibrarySongsDb:
    """Persistence sub-facade for library song and folder operations.

    Domain identity for library-scoped calls is the natural ``(name, root_path)``
    ``Library`` key; the storage ``library_id`` is resolved internally.
    Repository rows are mapped to :class:`Song` / :class:`LibraryFolder` before
    crossing this boundary; callers never need to know the storage row shape.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        song_repo: SongRepository,
        folder_repo: FolderRepository,
        song_state_repo: SongStateRepository,
        song_hydration_repo: SongHydrationRepository,
        library_repo: LibraryRepository,
    ) -> None:
        self._session = session
        self._song_repo = song_repo
        self._folder_repo = folder_repo
        self._song_state_repo = song_state_repo
        self._song_hydration_repo = song_hydration_repo
        self._library_repo = library_repo

    # ── natural-key resolution (persistence-internal) ────────────────────

    def _resolve_library_id(self, library: Library) -> int:
        """Resolve a ``Library``'s natural key to its storage row id.

        The id is used only to reach the row; it never crosses this facade.
        """
        row = self._library_repo.get_library_by_natural_key(library.name, library.root_path)
        if row is None:
            raise LookupError(f"Library {library.name!r} at {library.root_path!r} does not exist")
        return int(row["id"])

    # ── internal folder payload translation ──────────────────────────────

    def _folder_payload(self, library_id: int, folder: LibraryFolder) -> dict[str, Any]:
        """Translate a domain ``LibraryFolder`` into a storage folder payload.

        ``parent_path`` is resolved to the storage ``parent_id`` here; the id
        never leaves this facade. ``path`` is the library-relative path.
        """
        parent_id: int | None = None
        if folder.parent_path is not None:
            parent_id = self._folder_repo.get_folder_id_by_path(library_id, folder.parent_path)
        return {
            "path": folder.path,
            "name": folder.name,
            "parent_id": parent_id,
            "mtime": folder.mtime,
            "file_count": folder.file_count,
            "last_scanned_at": folder.last_scanned_at,
        }

    # ------------------------------------------------------------------
    # Numeric-handle identity bridge (P3, song-tag correction)
    # ------------------------------------------------------------------
    # Adapters for external/API or legacy aggregate handles that still carry a
    # numeric storage id. They resolve the row's private library FK and path to
    # the typed natural identity; no row, ``Song``, ``Library``, or storage id
    # crosses this boundary. Set-based (one song query + one library query per
    # batch), repository-owned short transactions, never a facade transaction.

    def resolve_song_identity(self, song_id: int) -> SongIdentity | None:
        """Resolve a song storage handle to its natural ``SongIdentity``.

        ``None`` when the song is missing or its owning library is missing (the
        identity cannot be constructed). The storage id is never exposed.
        """
        result = self.resolve_song_identities([song_id])
        return result.get(song_id)

    def resolve_song_identities(
        self,
        song_ids: Sequence[int],
    ) -> Mapping[int, SongIdentity]:
        """Resolve a batch of song storage handles to natural identities.

        Set-based: one ``get_songs_by_ids`` query and one library primary-key
        read for the distinct owning libraries. Unresolved song ids and songs
        whose owning library is missing are omitted; empty input yields ``{}``.
        """
        if not song_ids:
            return {}
        song_rows = self._song_repo.get_songs_by_ids(list(song_ids))
        library_ids = {int(r["library_id"]) for r in song_rows if r.get("library_id") is not None}
        if not library_ids:
            return {}
        libraries = self._library_repo.get_libraries_by_ids(list(library_ids))
        library_by_id = {int(r["id"]): r for r in libraries}
        result: dict[int, SongIdentity] = {}
        for row in song_rows:
            library_id = row.get("library_id")
            library_row = library_by_id.get(library_id) if library_id is not None else None
            if library_row is None:
                continue
            result[int(row["id"])] = SongIdentity(
                library=LibraryIdentity(name=library_row["name"], root_path=library_row["path"]),
                normalized_path=row["normalized_path"],
            )
        return result

    def resolve_library_identity(self, library_id: int) -> LibraryIdentity | None:
        """Resolve a numeric library handle to its natural reference."""
        result = self.resolve_library_identities([library_id])
        return result.get(library_id)

    def resolve_library_identities(
        self,
        library_ids: Sequence[int],
    ) -> Mapping[int, LibraryIdentity]:
        """Resolve numeric library handles to natural references (set-based)."""
        if not library_ids:
            return {}
        rows = self._library_repo.get_libraries_by_ids(list(library_ids))
        return {int(r["id"]): LibraryIdentity(name=r["name"], root_path=r["path"]) for r in rows}

    # ------------------------------------------------------------------
    # Song lookups
    # ------------------------------------------------------------------

    def get_song(self, song_id: int) -> Song | None:
        """Get a library song by its stable song identifier."""
        row = self._song_repo.get_song(song_id)
        return Song.from_row(row) if row is not None else None

    def get_song_by_path(self, path: str, library: Library) -> Song | None:
        """Get a library song by path within its owning library."""
        library_id = self._resolve_library_id(library)
        row = self._song_repo.get_song_by_path(path, library_id)
        return Song.from_row(row) if row is not None else None

    def get_song_by_normalized_path(self, normalized_path: str, library: Library) -> Song | None:
        """Get a song by its canonical normalized path within a library."""
        library_id = self._resolve_library_id(library)
        row = self._song_repo.get_song_by_normalized_path(library_id, normalized_path)
        return Song.from_row(row) if row is not None else None

    def find_song_by_path_any_library(self, path: str) -> Song | None:
        """Find a song by path when the caller intentionally searches all libraries."""
        row = self._song_repo.get_song_by_path_unscoped(path)
        return Song.from_row(row) if row is not None else None

    def list_songs_by_ids(self, song_ids: list[int]) -> list[Song]:
        """Return domain songs for the given song identifiers."""
        return [Song.from_row(row) for row in self._song_repo.get_songs_by_ids(song_ids)]

    def get_library_ids_for_songs(self, song_ids: list[int]) -> dict[int, int]:
        """Return mapping of song_id → library_id for the given song IDs."""
        return self._song_repo.get_library_ids_for_songs(song_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        """Count songs tagged since the given cutoff timestamp (epoch ms)."""
        return self._song_repo.count_recently_tagged(cutoff_ms)

    def list_library_song_ids(
        self,
        library: Library,
        *,
        limit: int | None = None,
    ) -> list[int]:
        """Return song IDs belonging to a library, with optional limit."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.list_library_song_ids(library_id, limit=limit)

    def list_songs(
        self,
        library: Library,
        *,
        limit: int | None = None,
    ) -> list[Song]:
        """Return domain songs belonging to a library, with optional limit."""
        library_id = self._resolve_library_id(library)
        return [Song.from_row(row) for row in self._song_repo.list_songs(library_id, limit=limit)]

    def count_songs(self, library: Library) -> int:
        """Count songs in a library."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.count_songs(library_id)

    def count_songs_for_library(self, library: Library) -> int:
        """Return the number of songs belonging to a library."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.count_songs(library_id)

    def find_library_song_by_chromaprint(
        self,
        library: Library,
        chromaprint: str,
    ) -> Song | None:
        """Find a library song by its Chromaprint fingerprint."""
        library_id = self._resolve_library_id(library)
        row = self._song_repo.find_song_by_chromaprint(library_id, chromaprint)
        return Song.from_row(row) if row is not None else None

    # ------------------------------------------------------------------
    # Song mutations
    # ------------------------------------------------------------------

    def add_song_to_library(self, library: Library, payload: dict) -> int:
        """Insert or update one library-song row.

        Returns the ``id`` of the upserted row.

        Raises:
            RuntimeError: If the upsert returns no song IDs.

        """
        library_id = self._resolve_library_id(library)
        song_ids = self._song_repo.upsert_songs_for_library(library_id, [payload])
        if not song_ids:
            msg = "add_song_to_library() expected one song id"
            raise RuntimeError(msg)
        # This overlaps the concurrent Song domain-identity migration in this
        # facade; retain that work while using the state intent operation.
        self._song_state_repo.initialize_song_states([song_ids[0]])
        return song_ids[0]

    def add_songs_to_library(
        self,
        library: Library,
        payloads: list[dict[str, Any]],
    ) -> list[int]:
        """Upsert songs and bootstrap initial states for newly created rows."""
        library_id = self._resolve_library_id(library)
        existing_paths = set(
            self._song_repo.list_existing_song_paths(
                library_id,
                [str(p["path"]) for p in payloads if "path" in p],
            )
        )
        self._song_repo.upsert_songs_for_library(library_id, payloads)
        song_ids_by_path = self._song_repo.get_song_ids_by_paths(
            library_id,
            [str(p["path"]) for p in payloads],
        )
        ordered_song_ids = [song_ids_by_path[str(p["path"])] for p in payloads]
        # Bootstrap state only for songs that were newly created
        for song_id, payload in zip(ordered_song_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                # Preserve concurrent domain-object changes in this method;
                # initialization is an intent operation, not state-table access.
                self._song_state_repo.initialize_song_states([song_id])
        return ordered_song_ids

    def update_songs(
        self,
        library: Library,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        """Reconcile library songs: upsert, init states, optionally remove missing.

        FK ON DELETE CASCADE handles derived data cleanup (streams, vectors,
        tags, state assignments) — no explicit derived-data removal needed.
        """
        library_id = self._resolve_library_id(library)
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
        existing_paths = set(self._song_repo.list_existing_song_paths(library_id, incoming_paths))

        # Upsert songs
        song_ids = self._song_repo.upsert_songs_for_library(library_id, payloads)
        new_count = 0
        for song_id, payload in zip(song_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                new_count += 1
                # This method is concurrently being migrated to domain Song
                # values; route only its state hook through the intent operation.
                self._song_state_repo.initialize_song_states([song_id])
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

    # ------------------------------------------------------------------
    # Song hydration (transactional intent)
    # ------------------------------------------------------------------

    def hydrate_song(self, input: HydrateSongInput) -> None:
        """Hydrate a single song atomically from an already-parsed input.

        Owns the complete logical unit of work: parsed ``nom:`` tags,
        entity/tag relationships, the accepted-but-ignored metadata-cache
        fields (never persisted, ADR-045), the optional one-shot duration,
        and the ``not_hydrated`` → ``hydrated`` state transition are
        written in one shared-session transaction and committed together.
        Any failure rolls back the entire unit, so a song is never left
        partially hydrated.

        Idempotent for repeated inputs: re-running the same input produces
        the same persisted assignments without side effects.

        This method owns its transaction boundary; callers must not manage
        transactions.

        Args:
            input: Fully-parsed hydration payload (see
                :class:`HydrateSongInput`). Values must already be
                extracted/parsed — persistence never calls extraction.

        """
        self._song_hydration_repo.hydrate_song(input)

    def hydrate_songs_batch(
        self,
        inputs: Sequence[HydrateSongInput],
        *,
        chunk_size: int = 100,
    ) -> int:
        """Hydrate a batch of songs, committing each bounded chunk atomically.

        Owns the complete logical unit of work per chunk. Each chunk of up
        to *chunk_size* inputs is committed as one shared-session
        transaction; a failure rolls back only its own chunk. Returns the
        number of inputs successfully committed.

        Idempotent for repeated inputs and harmless for duplicate values and
        duplicate song IDs within the batch.

        This method owns its transaction boundaries; callers must not manage
        transactions.

        Args:
            inputs: Fully-parsed hydration payloads.
            chunk_size: Maximum inputs per atomic chunk. Each chunk runs as
                set-based persistence, never per-song/per-tag lookups.

        """
        return self._song_hydration_repo.hydrate_songs_batch(inputs, chunk_size=chunk_size)

    def remove_song(self, song_id: int) -> None:
        """Remove one song. FK CASCADE handles derived streams and vectors.

        Args:
            song_id: Song row id to remove.

        """
        self._song_repo.delete_song(song_id)

    def remove_song_by_path(self, path: str, library: Library) -> None:
        """Remove a song by path within its owning library.

        Path is only unique together with the library; requiring the ``Library``
        here prevents an ambiguous path from selecting another library's song.
        """
        song_row = self.get_song_by_path(path, library)
        if song_row is None:
            return
        song_id = song_row.song_id
        self.remove_song(song_id)

    def list_existing_song_paths(self, library: Library, paths: list[str]) -> list[str]:
        """Return paths that already have rows in the given library."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.list_existing_song_paths(library_id, paths)

    # ------------------------------------------------------------------
    # Folder operations
    # ------------------------------------------------------------------

    def get_folder(self, library: Library, folder_path: str) -> LibraryFolder | None:
        """Return one folder identified by its library-relative path.

        The library natural key and relative path are the complete caller-facing
        identity. Storage folder ids and parent foreign keys remain inside the
        repository boundary.
        """
        library_id = self._resolve_library_id(library)
        return self._folder_repo.get_folder_by_path(library_id, folder_path)

    def list_folders_for_library(self, library: Library) -> list[LibraryFolder]:
        """Return all folders linked to a library as domain values."""
        library_id = self._resolve_library_id(library)
        return self._folder_repo.list_folders_for_library(library_id)

    def add_library_folder(self, library: Library, folder: LibraryFolder) -> LibraryFolder:
        """Create a folder and return the persisted domain value."""
        library_id = self._resolve_library_id(library)
        self._folder_repo.add_library_folder(library_id, self._folder_payload(library_id, folder))
        persisted = self._folder_repo.get_folder_by_path(library_id, folder.path)
        if persisted is None:
            raise LookupError(f"Folder {folder.path!r} was not persisted for library {library.name!r}")
        return persisted

    def replace_library_folder(self, library: Library, folder_path: str, folder: LibraryFolder) -> LibraryFolder:
        """Atomically replace one folder identified by its relative path.

        The replacement value must retain the path used for identification;
        changing a path is a distinct add/remove operation. Storage ids and
        parent foreign keys are resolved inside this facade.

        Raises ``LookupError`` when no folder exists at ``folder_path`` for the
        library. Returns the persisted replacement domain value.
        """
        if folder.path != folder_path:
            raise ValueError("folder_path must match folder.path for a path-identified replacement")
        library_id = self._resolve_library_id(library)
        folder_id = self._folder_repo.get_folder_id_by_path(library_id, folder_path)
        if folder_id is None:
            raise LookupError(f"No folder at {folder_path!r} for library {library.name!r}")
        self._folder_repo.replace_library_folder(library_id, folder_id, self._folder_payload(library_id, folder))
        persisted = self._folder_repo.get_folder_by_path(library_id, folder_path)
        if persisted is None:
            raise LookupError(f"Folder {folder_path!r} was not persisted for library {library.name!r}")
        return persisted

    def remove_library_folder(self, library: Library, folder_path: str) -> None:
        """Remove a folder identified by its library-relative path.

        Missing folders are intentionally treated as an idempotent no-op.
        """
        library_id = self._resolve_library_id(library)
        folder_id = self._folder_repo.get_folder_id_by_path(library_id, folder_path)
        if folder_id is None:
            return
        self._folder_repo.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library: Library, folders: list[LibraryFolder]) -> None:
        """Replace all folders linked to a library.

        Path-stable reconciliation preserves each folder row id, so songs that
        reference folders by id keep their linkage across the replacement.
        """
        library_id = self._resolve_library_id(library)
        payloads = [self._folder_payload(library_id, folder) for folder in folders]
        self._folder_repo.replace_library_folders(library_id, payloads)

    def list_songs_for_folder(
        self,
        library: Library,
        folder_rel_path: str,
    ) -> list[Song]:
        """Return domain songs within a specific folder of a library."""
        library_id = self._resolve_library_id(library)
        return [Song.from_row(row) for row in self._song_repo.list_songs_for_folder(library_id, folder_rel_path)]

    # ------------------------------------------------------------------
    # Track matching and maintenance
    # ------------------------------------------------------------------

    def list_tracks_for_matching(
        self,
        library: Library,
        *,
        limit: int | None = None,
    ) -> list[Song]:
        """Return domain songs suitable for track matching, with optional limit."""
        library_id = self._resolve_library_id(library)
        return [Song.from_row(row) for row in self._song_repo.list_tracks_for_matching(library_id, limit=limit)]

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
