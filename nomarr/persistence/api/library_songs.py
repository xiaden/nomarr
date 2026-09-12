"""Song and folder sub-facade for the library persistence surface.

Locator-addressed persistence facade: song operations are addressed by the
semantic ``SongIdentity`` locator (``LibraryIdentity.library_uuid`` plus the
library-relative normalized path, ADR-048). The private ``songs.id``,
``libraries.id``, and owning-library foreign keys are resolved internally only
to reach the row and never cross this facade; a locator that no longer resolves
is a deterministic miss (``None``/empty/``MISSING_LOCATOR``), never an integer
fallback.

The scalar write surface is exactly the three locator intents
``set_modified_time(SongIdentity, int)``, ``set_last_tagged(SongIdentity, int)``,
and ``set_chromaprint(SongIdentity, ChromaprintValue)``; each validates before
SQL, delegates to one short repository-owned transaction, and returns a
``FieldWriteResult`` carrying the seven-status business vocabulary (``UPDATED``,
``UNCHANGED``, ``STALE_VALUE``, ``INVALID_VALUE``, ``MISSING_LOCATOR``,
``INFRA_FAILURE``, ``AMBIGUOUS_COMMIT``). Operational failures propagate as
mapped domain exceptions rather than statuses, and no row, storage id, SQLSTATE,
or session detail is exposed. Legacy integer scalar writers/forwarders are
deleted, not wrapped.

Wired into ``LibraryDb`` as its ``songs`` namespace (namespaced-forwarding split
per DD-persistence-intent-facade-rebuild §Phase 1). Library-scoped methods accept
the domain ``Library`` natural key and resolve the storage ``library_id``
internally, and folder-facing methods use the ``LibraryFolder`` value object with
relative-path identity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.song_command_dataclass import (
    ChromaprintValue,
    FieldWriteResult,
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
        """Insert or update one library-song row and initialize only new rows.

        Single-command form of :meth:`add_songs_to_library_batch`; the upsert and the
        create-only state initialization run in one facade-owned transaction.

        Args:
            command: The typed song upsert intent; its scan metadata must be set.

        Returns:
            The resolved ``SongIdentity`` for the upserted song.

        Raises:
            ValueError: If ``command.scan`` is ``None``.
        """
        return self.add_songs_to_library_batch([command])[0]

    def add_songs_to_library_batch(self, commands: Sequence[SongUpsertInput]) -> list[SongIdentity]:
        """Upsert typed songs and initialize state only for new rows, atomically.

        The song-row upsert and the create-only state initialization share ONE
        facade-owned transaction: both repositories are called with ``commit=False``
        and the facade issues a single ``self._session.commit()``. Any failure rolls the
        whole transaction back and re-raises, so a row is never left committed without
        its state initialization.

        New song ids are resolved by path via ``get_song_ids_by_paths`` rather than from
        ``INSERT ... RETURNING`` order, which PostgreSQL does not guarantee.

        Args:
            commands: Typed upsert intents. All must target the same
                ``LibraryIdentity``; an empty sequence returns ``[]``.

        Returns:
            One ``SongIdentity`` per input command, in input order.

        Raises:
            ValueError: If ``commands`` span more than one library identity ("song
                batch must target one library"), or if any command's scan metadata
                is ``None``.
        """
        commands = list(commands)
        if not commands:
            return []
        library = commands[0].library
        if any(command.library != library for command in commands):
            raise ValueError("song batch must target one library")
        library_id = self._resolve_library_identity(library)
        payloads = [self._song_upsert_payload(command) for command in commands]
        try:
            existing = set(
                self._song_repo.list_existing_song_paths(library_id, [payload["path"] for payload in payloads])
            )
            song_ids = self._song_repo.upsert_songs_for_library(library_id, payloads, commit=False)
            if len(song_ids) != len(commands):
                raise RuntimeError("song batch upsert returned an unexpected row count")
            # Do not use the INSERT ... RETURNING row order to associate ids with
            # payloads. PostgreSQL does not guarantee that order matches VALUES.
            new_paths = [payload["path"] for payload in payloads if payload["path"] not in existing]
            new_ids: list[int] = []
            if new_paths:
                song_ids_by_path = self._song_repo.get_song_ids_by_paths(library_id, new_paths)
                new_ids = [song_ids_by_path[path] for path in new_paths]
            if new_ids:
                self._song_state_repo.initialize_song_states(new_ids, commit=False)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return [
            SongIdentity(library=command.library, normalized_path=payload["normalized_path"])
            for command, payload in zip(commands, payloads, strict=True)
        ]

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

    def set_modified_time(self, song: SongIdentity, modified_time_ms: int) -> FieldWriteResult:
        """Set a song's stored modified-time addressed by its locator.

        Pre-SQL validation: a non-``SongIdentity`` song, a non-``int``/``bool``
        value, or a negative timestamp returns ``FieldWriteResult("INVALID_VALUE")``
        without touching the session. A locator whose owning library does not
        resolve, or whose song does not resolve within that library, returns
        ``FieldWriteResult("MISSING_LOCATOR")`` and writes nothing. Otherwise the
        delegated repository monotonic write yields ``UPDATED``, ``UNCHANGED``
        (equal), or ``STALE_VALUE`` (lower than the stored value). Operational
        failures propagate as the mapped domain exceptions
        (``RetryableDatabaseError``, ``AmbiguousCommitError``,
        ``DatabaseStateError``); they are raised, not returned as
        ``FieldWriteResult`` statuses. No row, storage id, SQLSTATE, or session
        detail crosses this facade.
        """
        if (
            not isinstance(song, SongIdentity)
            or not isinstance(modified_time_ms, int)
            or isinstance(modified_time_ms, bool)
        ):
            return FieldWriteResult("INVALID_VALUE")
        if modified_time_ms < 0:
            return FieldWriteResult("INVALID_VALUE")
        library_id = self._try_resolve_library_identity(song.library)
        if library_id is None:
            return FieldWriteResult("MISSING_LOCATOR")
        return FieldWriteResult(
            self._song_repo.set_modified_time_by_locator(library_id, song.normalized_path, modified_time_ms)
        )

    def set_last_tagged(self, song: SongIdentity, tagged_at_ms: int) -> FieldWriteResult:
        """Set a song's stored last-tagged timestamp addressed by its locator.

        Pre-SQL validation: a non-``SongIdentity`` song, a non-``int``/``bool``
        value, or a negative timestamp returns ``FieldWriteResult("INVALID_VALUE")``
        without touching the session. A locator whose owning library does not
        resolve, or whose song does not resolve within that library, returns
        ``FieldWriteResult("MISSING_LOCATOR")`` and writes nothing. Otherwise the
        delegated repository monotonic write yields ``UPDATED``, ``UNCHANGED``
        (equal), or ``STALE_VALUE`` (lower than the stored value). Operational
        failures propagate as the mapped domain exceptions
        (``RetryableDatabaseError``, ``AmbiguousCommitError``,
        ``DatabaseStateError``); they are raised, not returned as
        ``FieldWriteResult`` statuses. No row, storage id, SQLSTATE, or session
        detail crosses this facade.
        """
        if not isinstance(song, SongIdentity) or not isinstance(tagged_at_ms, int) or isinstance(tagged_at_ms, bool):
            return FieldWriteResult("INVALID_VALUE")
        if tagged_at_ms < 0:
            return FieldWriteResult("INVALID_VALUE")
        library_id = self._try_resolve_library_identity(song.library)
        if library_id is None:
            return FieldWriteResult("MISSING_LOCATOR")
        return FieldWriteResult(
            self._song_repo.set_last_tagged_by_locator(library_id, song.normalized_path, tagged_at_ms)
        )

    def set_chromaprint(self, song: SongIdentity, value: ChromaprintValue) -> FieldWriteResult:
        """Guarded chromaprint replacement addressed by the song's locator.

        Pre-SQL validation: a non-``SongIdentity`` song or a non-``ChromaprintValue``
        value returns ``FieldWriteResult("INVALID_VALUE")`` without touching the
        session; ``ChromaprintValue`` itself rejects blank/whitespace values,
        blank provenance, and the mutually exclusive ``expected_absent`` /
        ``expected_value`` pair before any write. A locator whose owning library
        does not resolve, or whose song does not resolve within that library,
        returns ``FieldWriteResult("MISSING_LOCATOR")`` and writes nothing.
        Otherwise the delegated repository guarded replacement yields ``UPDATED``,
        ``UNCHANGED``, or ``STALE_VALUE`` according to the caller's
        ``expected_absent``/``expected_value`` precondition. Operational failures
        propagate as the mapped domain exceptions (``RetryableDatabaseError``,
        ``AmbiguousCommitError``, ``DatabaseStateError``); they are raised, not
        returned as ``FieldWriteResult`` statuses. No row, storage id, SQLSTATE,
        or session detail crosses this facade.
        """
        if not isinstance(song, SongIdentity) or not isinstance(value, ChromaprintValue):
            return FieldWriteResult("INVALID_VALUE")
        library_id = self._try_resolve_library_identity(song.library)
        if library_id is None:
            return FieldWriteResult("MISSING_LOCATOR")
        return FieldWriteResult(
            self._song_repo.set_chromaprint_by_locator(
                library_id,
                song.normalized_path,
                value.value,
                expected_value=value.expected_value,
                expected_absent=value.expected_absent,
            )
        )

    # ------------------------------------------------------------------
    # Song hydration (transactional intent)
    # ------------------------------------------------------------------

    def hydrate_song(self, song: SongIdentity, input: HydrateSongInput) -> None:
        """Hydrate a single song atomically from an already-parsed input.

        The song is addressed by its semantic locator; persistence resolves
        the locator to its private row key internally.

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
            song: Semantic locator identifying the song to hydrate.
            input: Fully-parsed hydration payload (see
                :class:`HydrateSongInput`). Values must already be
                extracted/parsed — persistence never calls extraction.

        """
        self._song_hydration_repo.hydrate_song(song, input)

    def hydrate_songs_batch(
        self,
        inputs: Sequence[tuple[SongIdentity, HydrateSongInput]],
        *,
        chunk_size: int = 100,
    ) -> int:
        """Hydrate a batch of locator-addressed songs, committing each bounded chunk atomically.

        Owns the complete logical unit of work per chunk. Each chunk of up
        to *chunk_size* inputs is committed as one shared-session
        transaction; a failure rolls back only its own chunk. Returns the
        number of inputs successfully committed.

        Idempotent for repeated inputs and harmless for duplicate values and
        duplicate song IDs within the batch.

        This method owns its transaction boundaries; callers must not manage
        transactions.

        Args:
            inputs: Locator-addressed hydration intents as
                ``(song_identity, payload)`` pairs.
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
