"""SongHydrationRepository — atomic transactional song hydration.

Composes the hydration write set (tag replacement, relationship writes,
metadata-cache update, optional one-shot duration fill, and the state
transition) into a single atomic unit of work.  A failure in any statement
rolls back every preceding write, so a song can never be left half-hydrated.

This module is the repo-level home for the intent that ``LibrarySongsDb``'s
``hydrate_song`` / ``hydrate_songs_batch`` facades will expose.  It receives
the shared scoped session plus the collaborator repos (song / tag /
song-tag / song-state) so every statement runs on the same session inside the
surrounding unit of work — mirroring how the codebase composes repositories.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, tuple_

from nomarr.helpers.exceptions import EntityNotFoundError
from nomarr.persistence.database.repo_helpers import atomic_unit_of_work
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dto.hydration_dto import HydrateSongInput
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository
    from nomarr.persistence.database.song_tag_repo import SongTagRepository
    from nomarr.persistence.database.tag_repo import TagRepository

# Tag namespace for parsed ``nom:`` ML tags (see DD-song-domain-repair:
# ``name`` stores the full namespaced key, ``namespace`` is ``'nom'`` for ML).
_NOM_NAMESPACE = "nom"
# Entity / canonical-metadata tags (artist, album, genre, year, …) live in the
# ordinary default namespace, stored as the literal ``"default"``.
_DEFAULT_NAMESPACE = "default"
logger = logging.getLogger(__name__)


def _expand_tag_rows(
    parsed_nom_tags: Mapping[str, Sequence[Any]] | None,
    entity_tags: Mapping[str, Sequence[Any]] | None,
) -> list[dict[str, Any]]:
    """Flatten parsed/entity tag mappings into ``(name, value, namespace)`` rows.

    Each mapping value is a sequence of values for a tag name; one row is
    produced per ``(name, value)`` pair.  Parsed ``nom:`` tags get the
    ``nom`` namespace, entity/canonical tags get the literal ``default``
    namespace.
    """
    rows: list[dict[str, Any]] = []
    rows.extend(
        {"name": str(name), "value": str(value), "namespace": _NOM_NAMESPACE}
        for name, values in (parsed_nom_tags or {}).items()
        for value in values
    )
    rows.extend(
        {"name": str(name), "value": str(value), "namespace": _DEFAULT_NAMESPACE}
        for name, values in (entity_tags or {}).items()
        for value in values
    )
    return rows


class SongHydrationRepository:
    """Repository-level composer for the transactional song-hydration intent."""

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        song_repo: SongRepository,
        tag_repo: TagRepository,
        song_tag_repo: SongTagRepository,
        song_state_repo: SongStateRepository,
        library_repo: LibraryRepository,
    ) -> None:
        """Store the shared session and collaborator repos.

        All collaborator statements run on *session* inside the surrounding
        unit of work; no repo opens its own transaction.
        """
        self._session = session
        self._song_repo = song_repo
        self._tag_repo = tag_repo
        self._song_tag_repo = song_tag_repo
        self._song_state_repo = song_state_repo
        self._library_repo = library_repo

    def hydrate_song(self, song: SongIdentity, input: HydrateSongInput) -> None:
        """Hydrate one song inside a single atomic unit of work.

        Sequence (state transition LAST = commit point):
          1. Verify the song exists (raises :class:`EntityNotFoundError`).
          2. Resolve/create all tags (parsed nom + entity) and replace the
             song's tag edges (full-replace, idempotent on retry).
          3. Update the supplied metadata-cache fields (no-op on the current
             schema — the songs table has no cache columns, per ADR-045).
          4. Fill ``duration_seconds`` only if the input supplies one AND the
             row does not already have one (one-shot).
          5. Transition ``not_hydrated`` → ``hydrated`` (preserves other axes).

        A failure in any statement rolls back all preceding writes.

        Args:
            song: Locator-addressed identity of the song to hydrate.
            input: The hydration payload (parsed nom tags, entity tags,
                   metadata-cache fields, optional duration).

        """
        with atomic_unit_of_work(self._session):
            resolved = self._resolve_song_id(song)
            song_id = int(resolved["id"])

            tag_rows = _expand_tag_rows(input.parsed_nom_tags, input.entity_tags)
            if tag_rows:
                tag_ids = self._tag_repo.get_or_create_tags_batch(tag_rows)
                edges = [
                    {
                        "song_id": song_id,
                        "tag_id": tag_ids[(r["namespace"], r["name"], r["value"])],
                    }
                    for r in tag_rows
                ]
                self._song_tag_repo.replace_song_tags_batch(edges)

            if input.metadata_cache:
                self._song_repo.update_song_metadata_fields(song_id, dict(input.metadata_cache))

            if input.duration_seconds is not None:
                self._song_repo.set_duration_if_unset(song_id, input.duration_seconds)

            # State transition is the LAST write (commit point).
            self._song_state_repo.transition_to_hydrated([song_id])

    def _resolve_song_ids_bulk(self, songs: Sequence[SongIdentity]) -> list[Mapping[str, Any]]:
        """Resolve a chunk of locators with one bounded joined query."""
        if not songs:
            return []
        keys = list(dict.fromkeys((song.library.library_uuid, song.normalized_path) for song in songs))
        rows = (
            self._session.execute(
                select(Song.__table__, Library.__table__.c.library_uuid)
                .join(Library.__table__, Library.__table__.c.id == Song.__table__.c.library_id)
                .where(tuple_(Library.__table__.c.library_uuid, Song.__table__.c.normalized_path).in_(keys))
            )
            .mappings()
            .all()
        )
        by_key = {(row["library_uuid"], row["normalized_path"]): row for row in rows}
        resolved: list[Mapping[str, Any]] = []
        for song in songs:
            row = by_key.get((song.library.library_uuid, song.normalized_path))
            if row is None:
                raise EntityNotFoundError("Song not found during hydration")
            resolved.append(dict(row))
        return resolved

    def _resolve_song_id(self, song: SongIdentity) -> Mapping[str, Any]:
        """Resolve a public locator to its private storage row, or raise.

        The generated ``songs.id`` is produced and consumed only inside
        persistence: it never leaves this repository as application identity.
        Raises :class:`EntityNotFoundError` when the library UUID or the
        ``(library, normalized_path)`` locator has no matching row.
        """
        library = self._library_repo.get_library_by_uuid(song.library.library_uuid)
        row = (
            self._song_repo.get_song_by_normalized_path(int(library["id"]), song.normalized_path)
            if library is not None
            else None
        )
        if row is None:
            raise EntityNotFoundError("Song not found during hydration")
        return row

    def hydrate_songs_batch(
        self,
        inputs: Sequence[tuple[SongIdentity, HydrateSongInput]],
        *,
        chunk_size: int = 100,
    ) -> int:
        """Hydrate many songs in bounded, atomically-committed chunks.

        Splits *inputs* into chunks of *chunk_size*.  Each chunk runs its tag
        lookup/inserts, relationship replacement, cache updates, duration fill,
        and state transitions with set-based statements (no per-song/per-tag
        loop), and commits atomically via one unit of work.  Returns the number
        of inputs successfully committed.

        Chunk-unit semantics (per CONTRACTS.md): each chunk is one atomic unit
        of work.  A missing song or a database error inside a chunk fails that
        chunk's unit, rolls back ALL of its writes, and is logged; remaining
        chunks still run and are counted normally.
        Duplicate song ids / tag values within a chunk and repeated identical
        inputs across calls are harmless (dedup + conflict-safe inserts +
        full-replace edges make the operation idempotent).

        Args:
            inputs: Locator-addressed hydration intents as
                ``(song_identity, payload)`` pairs.
            chunk_size: Maximum number of inputs per atomic chunk.

        Returns:
            Number of inputs whose chunk committed successfully.

        """
        if not inputs:
            return 0
        committed = 0
        for start in range(0, len(inputs), chunk_size):
            chunk = inputs[start : start + chunk_size]
            try:
                self._hydrate_chunk(chunk)
            except Exception:
                # Chunk unit already rolled back; keep going, but do not hide
                # the failed chunk from operators.
                logger.exception(
                    "Song hydration chunk failed",
                    extra={"hydration_count": len(chunk)},
                )
                continue
            committed += len(chunk)
        return committed

    def _hydrate_chunk(self, inputs: Sequence[tuple[SongIdentity, HydrateSongInput]]) -> None:
        """Run one chunk of hydrations as a single atomic unit of work."""
        with atomic_unit_of_work(self._session):
            resolved = self._resolve_song_ids_bulk([song for song, _ in inputs])
            song_ids = [row["id"] for row in resolved]
            # Build all tag rows + edges across the whole chunk (set-based).
            all_tag_rows: list[dict[str, Any]] = []
            tag_rows_by_song: dict[int, list[dict[str, Any]]] = {}
            for song_id, (_, input) in zip(song_ids, inputs, strict=True):
                rows = _expand_tag_rows(input.parsed_nom_tags, input.entity_tags)
                tag_rows_by_song.setdefault(song_id, []).extend(rows)
                all_tag_rows.extend(rows)

            edges: list[dict[str, Any]] = []
            if all_tag_rows:
                unique_tag_rows = list(
                    {(row["namespace"], row["name"], row["value"]): row for row in all_tag_rows}.values()
                )
                tag_ids = self._tag_repo.get_or_create_tags_batch(unique_tag_rows)
                for song_id, rows in tag_rows_by_song.items():
                    edges.extend(
                        {
                            "song_id": song_id,
                            "tag_id": tag_ids[(r["namespace"], r["name"], r["value"])],
                        }
                        for r in rows
                    )
            self._song_tag_repo.replace_song_tags_batch(edges, song_ids=song_ids)

            # Metadata-cache updates (no-op on current schema per ADR-045).
            cache_by_song: dict[int, dict[str, Any]] = {
                song_id: dict(input.metadata_cache)
                for song_id, (_, input) in zip(song_ids, inputs, strict=True)
                if input.metadata_cache
            }
            self._song_repo.update_song_metadata_fields_batch(cache_by_song)

            # One-shot duration fill across the chunk (single statement).
            durations = {
                song_id: input.duration_seconds
                for song_id, (_, input) in zip(song_ids, inputs, strict=True)
                if input.duration_seconds is not None
            }
            self._song_repo.set_durations_if_unset(durations)

            # State transition is the LAST write (commit point).
            self._song_state_repo.transition_to_hydrated(song_ids)
