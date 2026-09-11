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
    SongPathUpdate,
    SongRemoval,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.mappers.song_mapper import song_row_to_domain

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryFolder
    from nomarr.helpers.dataclasses.song_dataclass import Song
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
        """Resolve a domain ``Library``'s immutable UUID to its storage row id.

        The id is used only to reach the row; it never crosses this facade. A
        domain ``Library`` with no ``library_uuid`` (for example an unsaved
        configuration input) cannot address persistent songs and is treated as
        missing.
        """
        if library.library_uuid is None:
            raise LookupError(f"Library {library.name!r} has no library_uuid")
        row = self._library_repo.get_library_by_uuid(library.library_uuid)
        if row is None:
            raise LookupError(f"Library {library.library_uuid!r} does not exist")
        return int(row["id"])

    def _resolve_library_identity(self, identity: LibraryIdentity) -> int:
        """Resolve a UUID ``LibraryIdentity`` to its private storage row id.

        Dedicated resolver for the typed single-song command; keeps the
        ``Library``-typed ``_resolve_library_id`` used by unrelated methods
        alongside it. The id is used only to reach the row and never crosses this
        facade. An unknown ``library_uuid`` is a missing library (``LookupError``),
        never a fabricated lookup.
        """
        row = self._library_repo.get_library_by_uuid(identity.library_uuid)
        if row is None:
            raise LookupError(f"Library {identity.library_uuid!r} does not exist")
        return int(row["id"])

    def _try_resolve_library_identity(self, identity: LibraryIdentity) -> int | None:
        """Resolve a UUID ``LibraryIdentity`` to its private storage row id.

        Unlike ``_resolve_library_identity`` this returns ``None`` (never raises)
        when the library cannot be resolved. It backs locator reads where an
        unresolvable owning library is a deterministic miss, not an error. The id
        never crosses this facade.
        """
        row = self._library_repo.get_library_by_uuid(identity.library_uuid)
        if row is None:
            return None
        return int(row["id"])

    def _resolve_song_id(self, identity: SongIdentity) -> int | None:
        """Resolve a semantic song locator to a private storage id."""
        library_id = self._try_resolve_library_identity(identity.library)
        if library_id is None:
            return None
        row = self._song_repo.get_song_by_normalized_path(library_id, identity.normalized_path)
        return int(row["id"]) if row is not None else None

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
                library=LibraryIdentity(
                    library_uuid=library_row["library_uuid"],
                    name=library_row["name"],
                    root_path=library_row["path"],
                ),
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
        return {
            int(r["id"]): LibraryIdentity(
                library_uuid=r["library_uuid"],
                name=r["name"],
                root_path=r["path"],
            )
            for r in rows
        }

    # ------------------------------------------------------------------
    # Song lookups
    # ------------------------------------------------------------------

    def get_song(self, identity: SongIdentity) -> Song | None:
        """Get a song addressed by its natural locator ``SongIdentity``.

        ``identity`` is the mutable, request-scoped SongLocator (ADR-048); the
        owning library's storage id and the generated ``songs.id`` are resolved
        privately and never cross this facade. A locator whose library or song
        no longer resolves is a deterministic ``None`` miss, never an error and
        never an integer fallback.
        """
        library_id = self._try_resolve_library_identity(identity.library)
        if library_id is None:
            return None
        row = self._song_repo.get_song_by_normalized_path(library_id, identity.normalized_path)
        return song_row_to_domain(row) if row is not None else None

    def get_song_by_path(self, path: str, library: Library) -> Song | None:
        """Get a library song by path within its owning library."""
        library_id = self._resolve_library_id(library)
        row = self._song_repo.get_song_by_path(path, library_id)
        return song_row_to_domain(row) if row is not None else None

    def get_song_by_normalized_path(
        self,
        library: LibraryIdentity,
        normalized_path: str,
    ) -> Song | None:
        """Get a song by its canonical normalized path within a library.

        ``library`` is the natural ``LibraryIdentity`` locator; a library or
        song that does not resolve is a deterministic ``None`` miss.
        """
        library_id = self._try_resolve_library_identity(library)
        if library_id is None:
            return None
        row = self._song_repo.get_song_by_normalized_path(library_id, normalized_path)
        return song_row_to_domain(row) if row is not None else None

    def find_song_by_path_any_library(self, path: str) -> Song | None:
        """Find a song by path when the caller intentionally searches all libraries."""
        row = self._song_repo.get_song_by_path_unscoped(path)
        return song_row_to_domain(row) if row is not None else None

    def list_songs_by_identity(self, identities: Sequence[SongIdentity]) -> list[Song]:
        """Return domain songs for the given natural locators (ADR-048).

        Order-preserving: each returned song corresponds to its input locator in
        the same position. Locators whose owning library or song cannot be
        resolved are omitted deterministically; empty input yields ``[]``. No
        generated ``songs.id`` or library row id is accepted or returned.
        """
        if not identities:
            return []
        # Resolve each distinct owning library UUID to its private id.
        distinct_uuids = list(dict.fromkeys(ident.library.library_uuid for ident in identities))
        if not distinct_uuids:
            return []
        library_ids = self._library_repo.get_library_ids_by_uuids(distinct_uuids)
        # Collect (library_id, normalized_path) targets for resolvable libraries.
        targets: list[tuple[int, str]] = []
        target_ids: list[tuple[int, str]] = []
        for ident in identities:
            lib_id = library_ids.get(ident.library.library_uuid)
            if lib_id is None:
                continue
            targets.append((lib_id, ident.normalized_path))
            target_ids.append((lib_id, ident.normalized_path))
        if not targets:
            return []
        # Resolve the target normalized paths to private song ids and fetch rows
        # once; then map back through the input order.
        song_id_by_loc = self._song_repo.get_song_ids_by_normalized_paths(targets)
        found_ids = list(set(song_id_by_loc.values()))
        rows_by_id: dict[int, Any] = {}
        if found_ids:
            rows_by_id = {int(r["id"]): r for r in self._song_repo.get_songs_by_ids(found_ids)}
        result: list[Song] = []
        for lib_id, normalized_path in target_ids:
            song_row_id = song_id_by_loc.get((lib_id, normalized_path))
            row = rows_by_id.get(song_row_id) if song_row_id is not None else None
            if row is None:
                continue
            result.append(song_row_to_domain(row))
        return result

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
        library: LibraryIdentity,
        *,
        limit: int | None = None,
    ) -> list[Song]:
        """Return domain songs belonging to a library, with optional limit.

        ``library`` is the required natural ``LibraryIdentity`` locator (there
        is no cross-library listing primitive; CONTRACTS §3). An unresolvable
        library is a deterministic ``LookupError`` (typed error), never a row or
        integer fallback.
        """
        library_id = self._resolve_library_identity(library)
        return [song_row_to_domain(row) for row in self._song_repo.list_songs(library_id, limit=limit)]

    def count_songs(self, library: Library) -> int:
        """Count songs in a library."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.count_songs(library_id)

    def count_songs_for_library(self, library: Library) -> int:
        """Return the number of songs belonging to a library."""
        library_id = self._resolve_library_id(library)
        return self._song_repo.count_songs(library_id)

    def list_songs_with_state(
        self,
        state: str,
        *,
        library: LibraryIdentity | None = None,
        order_by_activity: bool = False,
        limit: int | None = None,
    ) -> list[SongStateCandidate]:
        """Return typed candidates for songs currently in *state* (CONTRACTS §3/§5).

        Each result carries the semantic ``SongStateCandidate`` (``SongIdentity``
        locator + domain ``Song`` + sorted state-name membership) only. Storage
        rows, assignment/edge rows, ``songs.id``, and ``library_id`` never cross
        this boundary; private joins/ids are resolved internally from
        ``song_state_repo`` / ``song_repo`` / ``library_repo`` primitives.

        Deterministic behavior:
          * no song in *state* (or an unknown/blank state) -> ``[]``;
          * duplicate state rows and duplicate song rows are de-duplicated by
            persistence identity, preserving the first state-repository order;
          * *library* given and unresolvable -> ``[]`` (a scoped miss);
          * *library* ``None`` -> candidates across all libraries, ordered by
            ``(library name, root_path, normalized_path)``;
          * ``order_by_activity=True`` -> newest scan/tag activity first,
            tie-broken by library name/root and normalized path;
          * ``limit`` applied after ordering.

        A missing owning library row is an unresolvable/stale locator and is
        omitted, while malformed row-to-domain or locator data raises its
        typed mapper/value error; raw rows are never returned as a fallback.
        The read does not hydrate songs or mutate state. No caller
        transaction/session is opened or managed.
        """
        if not isinstance(state, str) or not state.strip():
            return []
        song_ids = self._song_state_repo.list_songs_in_state(state)
        if not song_ids:
            return []
        if library is not None:
            library_id = self._try_resolve_library_identity(library)
            if library_id is None:
                return []
            owning = self._song_repo.get_library_ids_for_songs(song_ids)
            song_ids = [sid for sid in song_ids if owning.get(sid) == library_id]
            if not song_ids:
                return []
        unique_ids = list(dict.fromkeys(song_ids))
        rows = self._song_repo.get_songs_by_ids(unique_ids)
        rows_by_id: dict[int, Any] = {int(r["id"]): r for r in rows}
        if not rows_by_id:
            return []
        memberships = self._song_state_repo.get_song_states_for_songs(list(rows_by_id))
        library_ids = {int(r["library_id"]) for r in rows_by_id.values()}
        library_rows = (
            {int(r["id"]): r for r in self._library_repo.get_libraries_by_ids(list(library_ids))} if library_ids else {}
        )

        candidates: list[SongStateCandidate] = []
        seen: set[tuple[int, str]] = set()
        for row in rows_by_id.values():
            library_id = int(row["library_id"])
            normalized_path = row["normalized_path"]
            if (library_id, normalized_path) in seen:
                continue
            seen.add((library_id, normalized_path))
            library_row = library_rows.get(library_id)
            if library_row is None:
                # Cannot form a natural locator without the owning library's key.
                continue
            identity = SongIdentity(
                library=LibraryIdentity(
                    library_uuid=library_row["library_uuid"],
                    name=library_row["name"],
                    root_path=library_row["path"],
                ),
                normalized_path=normalized_path,
            )
            song = song_row_to_domain(row)
            states = tuple(sorted(memberships.get(int(row["id"]), set())))
            candidates.append(SongStateCandidate(identity=identity, song=song, states=states))

        if order_by_activity:

            def _activity(candidate: SongStateCandidate) -> int:
                return max(candidate.song.scanned_at or 0, candidate.song.last_tagged_at or 0)

            candidates.sort(
                key=lambda c: (
                    -_activity(c),
                    c.identity.library.name or "",
                    c.identity.normalized_path,
                )
            )
        else:
            candidates.sort(
                key=lambda c: (
                    c.identity.library.name or "",
                    c.identity.library.root_path or "",
                    c.identity.normalized_path,
                )
            )
        if limit is not None:
            return candidates[:limit]
        return candidates

    def find_library_song_by_chromaprint(
        self,
        library: Library,
        chromaprint: str,
    ) -> Song | None:
        """Find a library song by its Chromaprint fingerprint."""
        library_id = self._resolve_library_id(library)
        row = self._song_repo.find_song_by_chromaprint(library_id, chromaprint)
        return song_row_to_domain(row) if row is not None else None

    # ------------------------------------------------------------------
    # Song mutations
    # ------------------------------------------------------------------

    def _song_upsert_payload(self, command: SongUpsertInput) -> dict[str, Any]:
        """Map a sealed single-song command to a private repository row payload.

        Maps only the approved persistence fields. State flags and the unused
        ``folder_id`` assignment are intentionally omitted so update behavior is
        unchanged. ``chromaprint`` is a persistence-owned ``None`` default
        (matching the value the prior single-song payload stored), and
        ``scanned_at`` defaults to the current time unless ``command.scan``
        supplies one.

        A scan-less command is rejected: the ``songs`` row contract requires the
        scan-sourced ``file_size``/``modified_time`` columns, which are non-null
        with no persistence default and no other source, so a command without
        ``scan`` cannot produce an insertable row. The sole production caller
        always supplies scan metadata; scan-less commands were never a supported
        legacy path, so no prior error behavior is displaced.

        Raises:
            ValueError: If ``command.scan`` is ``None``.

        """
        scan = command.scan
        if scan is None:
            raise ValueError(
                "add_song_to_library() requires scan metadata: file_size/"
                "modified_time are non-null songs columns with no persistence "
                "default and no other source"
            )
        payload: dict[str, Any] = {
            "path": command.path,
            "normalized_path": scan.normalized_path,
            "file_size": scan.file_size,
            "modified_time": scan.modified_time,
            "duration_seconds": scan.duration_seconds,
            "chromaprint": None,
            "last_tagged_at": command.last_tagged_at,
            "scanned_at": now_ms().value,
        }
        if scan.scanned_at is not None:
            payload["scanned_at"] = scan.scanned_at
        return payload

    def add_song_to_library(self, command: SongUpsertInput) -> SongIdentity:
        """Insert or update one library-song row from a typed command.

        Persistence alone resolves ``command.library`` to the private library row
        id, maps the command to the repository's private row payload, applies
        defaults, invokes the private upsert, and initializes states with the
        private returned song id. The generated storage id never leaves this
        facade.

        Returns the natural ``SongIdentity`` built from ``command.library`` and the
        normalized path selected by the same command/default mapping used for the
        upsert.

        Raises:
            LookupError: If the command's library does not exist.
            ValueError: If the command omits scan metadata (its row cannot
                satisfy the non-null scan-sourced column contract).
            RuntimeError: If the upsert returns no song IDs.

        """
        library_id = self._resolve_library_identity(command.library)
        payload = self._song_upsert_payload(command)
        song_ids = self._song_repo.upsert_songs_for_library(library_id, [payload])
        if not song_ids:
            msg = "add_song_to_library() expected one song id"
            raise RuntimeError(msg)
        # This overlaps the concurrent Song domain-identity migration in this
        # facade; retain that work while using the state intent operation. The
        # generated id is consumed only by the private state initializer.
        self._song_state_repo.initialize_song_states([song_ids[0]])
        return SongIdentity(library=command.library, normalized_path=payload["normalized_path"])

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

        # Do not use the INSERT ... RETURNING row order to associate ids with
        # payloads. PostgreSQL does not guarantee that order matches VALUES.
        self._song_repo.upsert_songs_for_library(library_id, payloads)
        song_ids_by_path = self._song_repo.get_song_ids_by_paths(library_id, incoming_paths)
        ordered_song_ids = [song_ids_by_path[str(payload["path"])] for payload in payloads]

        new_count = 0
        for song_id, payload in zip(ordered_song_ids, payloads, strict=True):
            if payload.get("path") not in existing_paths:
                new_count += 1
                # This method is concurrently being migrated to domain Song
                # values; route only its state hook through the intent operation.
                self._song_state_repo.initialize_song_states([song_id])
        result["added"] = new_count
        result["updated"] = len(ordered_song_ids) - new_count

        if remove_missing:
            current_ids = set(self._song_repo.list_library_song_ids(library_id))
            upserted_ids = set(ordered_song_ids)
            to_remove = sorted(current_ids - upserted_ids)
            if to_remove:
                self._song_repo.remove_songs(to_remove)
                # FK CASCADE handles song_state_assignments, song_tags, etc.
            result["removed"] = len(to_remove)

        return result

    def move_library_song(self, command: SongPathUpdate) -> SongIdentity | None:
        """Atomically relocate one existing Song from its source locator.

        One persistence intent for a complete Song move addressed by the **source
        locator** ``command.song_identity`` (``SongIdentity(library,
        normalized_path)``; ADR-048). Persistence alone resolves ``(library,
        source_normalized_path)`` to the private library row id and song row, then
        applies the destination physical ``new_path`` and the complete scan
        snapshot (destination normalized path, file size, mtime, duration,
        validity, scan timestamp) to the existing song row *in place* in one
        repository transaction: path, normalized path, and scan metadata commit
        together or not at all, so the natural locators and scan metadata can never
        diverge after a partial failure. The source-locator predicates participate
        in the same statement/transaction; no separate lookup race.

        ``song_identity`` is a mutable, request-scoped locator, not a stable
        identity. This never inserts, deletes, or recreates a row, and Song
        associations (tags, state assignments, streams, embeddings) remain
        attached. No generated row id, library id, repository, session, or raw row
        crosses this facade.

        Returns the destination ``SongIdentity`` (``command.song_identity.library``
        with the destination normalized path) when the move commits, or ``None``
        when the source locator is stale/missing (its library or song no longer
        resolves). ``None`` is a safe no-op miss — no replacement row is fabricated
        and no other row is relocated (ADR-048 §5). This supersedes the historical
        ``LookupError`` taxonomy for move addressing.

        Raises:
            ValueError: If ``command.scan.normalized_path`` is ``None``. The
                ``songs.normalized_path`` column is NOT NULL (with a
                ``(library_id, normalized_path)`` unique constraint), so an
                unrepresentable destination (the defensive out-of-root move case)
                is rejected atomically *before* any write rather than stored as
                ``None`` or silently dropped from the atomic update.
            DuplicateEntityError: If the destination collides on
                ``(library_id, path)`` or ``(library_id, normalized_path)`` (the
                row keeps its owning library on a move), mapped from persistence;
                the whole move rolls back leaving the original row unchanged.

        """
        source = command.song_identity
        scan = command.scan
        if scan.normalized_path is None:
            raise ValueError(
                "move_library_song() requires a normalized_path: songs."
                "normalized_path is NOT NULL and cannot store None"
            )
        # Resolve the source library's private id privately. A source locator whose
        # owning library cannot be resolved is a stale/missing source -> None miss
        # (ADR-048), never a fabricated integer fallback.
        library_row = self._library_repo.get_library_by_uuid(source.library.library_uuid)
        if library_row is None:
            return None
        library_id = int(library_row["id"])
        payload: dict[str, Any] = {
            "path": command.new_path,
            "normalized_path": scan.normalized_path,
            "file_size": scan.file_size,
            "modified_time": scan.modified_time,
            "duration_seconds": scan.duration_seconds,
            "is_valid": 1 if scan.is_valid else 0,
            "scanned_at": scan.scanned_at if scan.scanned_at is not None else now_ms().value,
        }
        # One statement/transaction matching the source locator, never an integer
        # id lookup. Source predicates live in the same UPDATE.
        if not self._song_repo.move_song(library_id, source.normalized_path, payload):
            return None
        return SongIdentity(library=source.library, normalized_path=scan.normalized_path)

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

    def remove_song(self, command: SongRemoval) -> bool:
        """Remove one song addressed by its natural locator (ADR-048).

        ``command.song_identity`` is the mutable SongLocator ``SongIdentity``;
        the owning library's storage id and the generated ``songs.id`` are
        resolved privately and consumed only by the private delete. FK CASCADE
        handles derived streams and vectors.

        Returns ``True`` when the song was found and removed, ``False`` when the
        locator no longer resolves (missing library or song) — a deterministic
        miss, never an error and never an integer fallback.
        """
        identity = command.song_identity
        library_id = self._try_resolve_library_identity(identity.library)
        if library_id is None:
            return False
        row = self._song_repo.get_song_by_normalized_path(library_id, identity.normalized_path)
        if row is None:
            return False
        self._song_repo.delete_song(int(row["id"]))
        return True

    def remove_song_by_path(self, path: str, library: Library) -> None:
        """Remove a song by path within its owning library.

        Path is only unique together with the library; requiring the ``Library``
        here prevents an ambiguous path from selecting another library's song.
        The song is located by resolving the library's private row id and its
        physical ``path``; the generated song row id is consumed only by the
        private delete and never crosses this facade (ADR-048).
        """
        library_id = self._resolve_library_id(library)
        row = self._song_repo.get_song_by_path(path, library_id)
        if row is None:
            return
        self._song_repo.delete_song(int(row["id"]))

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
        return [song_row_to_domain(row) for row in self._song_repo.list_songs_for_folder(library_id, folder_rel_path)]

    def update_song_calibration_hash(self, song: SongIdentity, calibration_hash: str) -> bool:
        """Persist a calibration hash addressed by semantic song identity."""
        song_id = self._resolve_song_id(song)
        if song_id is None:
            return False
        return self._song_repo.update_song_calibration_hash(song_id, calibration_hash)

    def update_song_calibration_hashes(
        self,
        updates: Sequence[tuple[SongIdentity, str]],
    ) -> int:
        """Persist a batch of hashes atomically; stale locators are no-ops."""
        if not updates:
            return 0
        resolved: dict[int, str] = {}
        for identity, value in updates:
            song_id = self._resolve_song_id(identity)
            if song_id is not None:
                resolved[song_id] = value
        if not resolved:
            return 0
        return self._song_repo.update_song_calibration_hashes(resolved)

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
        return [song_row_to_domain(row) for row in self._song_repo.list_tracks_for_matching(library_id, limit=limit)]

    def list_orphaned_song_ids(self) -> list[int]:
        """List song IDs that have no matching library-song row."""
        return self._song_repo.list_orphaned_song_ids()

    def prune_orphaned_songs(self) -> int:
        """Delete every song row that has no owning library row; return the count.

        Locator-free maintenance intent (plan C/H): an orphaned song has no
        resolvable ``SongIdentity`` because its owning library is already gone,
        so the sole way to address it is a persistence-private row handle. This
        method resolves those handles privately and deletes each orphan's full
        derived set (FK CASCADE) without ever exposing a generated ``songs.id`` or
        ``library_id``. It returns only the number of rows removed, is distinct
        from the ordinary ``SongRemoval`` intent, and must not be used for
        user-addressed deletes.
        """
        orphan_ids = self._song_repo.list_orphaned_song_ids()
        for song_id in orphan_ids:
            self._song_repo.delete_song(int(song_id))
        return len(orphan_ids)

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
