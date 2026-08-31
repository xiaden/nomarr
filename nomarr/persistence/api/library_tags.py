"""Tag sub-facade for the library persistence surface.

Holds all tag-domain (``tags`` table) and song-tag edge (``song_tags``
junction) intent methods. Wired into ``LibraryDb`` as its ``tags``
namespace.

Domain boundary (per artifacts/designs/parts/song-domain-repair/CONTRACTS.md —
song-tag migration contract, 2026-08-30):

- Tags are addressed by ``TagRef(name, value, namespace)``, never by a
  database primary key.
- Songs are addressed by ``SongIdentity(library: LibraryIdentity, normalized_path)`` (natural library key + normalized path), resolved internally to the storage song id.
- Read results are typed domain values (``TagRef``, ``SongTagAssignment``,
  ``TagUsage``, ``RelinkResult``, ``TagCleanupResult``) — no ``TagRow``,
  ``SongRow``, or raw ``dict`` projections leak to callers.
- Mutations resolve natural keys set-based and delegate transaction ownership
  to the repository layer; the facade exposes no transaction context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dataclasses.song_tag_dataclass import (
    RelinkResult,
    SongTagAssignment,
    TagCleanupResult,
    TagRef,
    TagUsage,
)
from nomarr.persistence.mappers.song_tag_mapper import (
    song_from_row,
    song_tag_assignment_from_batch_row,
    song_tag_assignment_from_row,
    song_tag_match_from_row,
    tag_identity_from_row,
    tag_usage_from_row,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.song_tag_repo import SongTagRepository
    from nomarr.persistence.database.tag_repo import TagRepository


class LibraryTagsDb:
    """Persistence sub-facade for tag and song-tag edge operations.

    Domain identity: ``TagRef(name, value, namespace)`` tag natural key
    and ``SongIdentity(library: LibraryIdentity, normalized_path)`` song
    natural key. Tag and song rows are keyed by integer primary keys internally;
    callers address tags and songs exclusively by their domain identities.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        tag_repo: TagRepository,
        song_tag_repo: SongTagRepository,
        song_repo: SongRepository,
        library_repo: LibraryRepository,
    ) -> None:
        self._session = session
        self._tag_repo = tag_repo
        self._song_tag_repo = song_tag_repo
        self._song_repo = song_repo
        self._library_repo = library_repo

    # ------------------------------------------------------------------
    # Identity helpers (set-based; never leak storage ids to callers)
    # ------------------------------------------------------------------

    def _resolve_song_id(self, song: SongIdentity) -> int | None:
        """Resolve one song natural key to its storage id, or ``None`` if absent.

        ``SongIdentity.library`` is a natural ``LibraryIdentity`` reference, so
        it is first resolved to a library primary key, then the song's
        normalized path is resolved within that library.
        """
        root_path = song.library.root_path
        if root_path is None:
            return None
        library_row = self._library_repo.get_library_by_natural_key(
            song.library.name,
            root_path,
        )
        if library_row is None:
            return None
        row = self._song_repo.get_song_by_normalized_path(library_row["id"], song.normalized_path)
        return row["id"] if row is not None else None

    def _resolve_song_ids_map(self, songs: Sequence[SongIdentity]) -> dict[SongIdentity, int]:
        """Resolve a batch of song natural keys to storage ids, keyed by identity.

        Set-based: libraries are resolved in one query and songs in one query —
        no per-song/per-library SQL loop in the facade (P2-S6).
        """
        if not songs:
            return {}
        identity_keys: dict[SongIdentity, tuple[str, str]] = {}
        for s in songs:
            root_path = s.library.root_path
            if root_path is None:
                continue
            identity_keys[s] = (s.library.name, root_path)
        library_id_map = self._library_repo.get_library_ids_by_natural_keys(list(set(identity_keys.values())))
        resolved = [s for s in identity_keys if identity_keys[s] in library_id_map]
        song_id_map = self._song_repo.get_song_ids_by_normalized_paths(
            [(library_id_map[identity_keys[s]], s.normalized_path) for s in resolved]
        )
        return {
            s: song_id_map[(library_id_map[identity_keys[s]], s.normalized_path)]
            for s in resolved
            if (library_id_map[identity_keys[s]], s.normalized_path) in song_id_map
        }

    def _resolve_song_ids(self, songs: Sequence[SongIdentity]) -> list[int]:
        """Resolve a batch of song natural keys to storage ids (set-based)."""
        return list(self._resolve_song_ids_map(songs).values())

    # ------------------------------------------------------------------
    # Tag lookups
    # ------------------------------------------------------------------

    def get_tag(self, identity: TagRef) -> TagRef | None:
        """Find a tag by its complete domain identity, never exposing its database ID.

        Matches the full ``(name, value, namespace)`` natural key exactly. The
        identity is resolved set-based via ``get_tag_ids_by_identities`` (not the
        value-blind name+namespace-only ``get_tag_by_name`` fetch), then the
        matching row is read by primary key, so a shared ``(name, namespace)``
        pair with multiple values resolves to the exact tag for each value and
        ``None`` for a non-matching value.
        """
        tag_ids = self._tag_repo.get_tag_ids_by_identities(
            [{"name": identity.name, "value": str(identity.value), "namespace": identity.namespace}]
        )
        key = (identity.name, str(identity.value), identity.namespace)
        tag_id = tag_ids.get(key)
        if tag_id is None:
            return None
        rows = self._tag_repo.get_tags_by_ids([tag_id])
        if not rows:
            return None
        row = rows[0]
        return TagRef(name=row["name"], value=row["value"], namespace=row["namespace"])

    def ensure_tag(self, identity: TagRef) -> TagRef:
        """Find or create a tag identified by its domain identity, returning it (never an ID)."""
        self._tag_repo.get_or_create_tag(identity.name, str(identity.value), identity.namespace)
        return identity

    def list_tags_for_song(self, song: SongIdentity) -> tuple[SongTagAssignment, ...]:
        """Return domain tag assignments for a song identified by its natural key.

        Empty tuple when the song does not exist or has no tags.
        """
        song_id = self._resolve_song_id(song)
        if song_id is None:
            return ()
        rows = self._song_tag_repo.get_tags_for_song(song_id)
        return tuple(song_tag_assignment_from_row(r, song=song) for r in rows)

    def list_all_tag_names(self, limit: int) -> list[str]:
        """Return distinct tag names, up to the given limit."""
        return self._tag_repo.list_all_tag_names(limit=limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TagRef, ...]:
        """Return domain tag identities, optionally filtered by exact name and value search."""
        rows = self._tag_repo.list_tags(name=name, search=search, limit=limit, offset=offset)
        return tuple(tag_identity_from_row(r) for r in rows)

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
    ) -> tuple[TagUsage, ...]:
        """List tags with pre-computed song counts as typed ``TagUsage`` values."""
        rows = self._tag_repo.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)
        return tuple(tag_usage_from_row(r) for r in rows)

    def list_genre_tags_for_songs(
        self,
        songs: Sequence[SongIdentity],
    ) -> tuple[SongTagAssignment, ...]:
        """Return genre tags assigned to any of the given songs (domain assignments)."""
        song_ids = self._resolve_song_ids(songs)
        if not song_ids:
            return ()
        rows = self._song_tag_repo.get_genre_tags_for_songs(song_ids)
        return tuple(song_tag_assignment_from_row(r) for r in rows)

    def list_song_tags_for_songs(
        self,
        songs: Sequence[SongIdentity],
        *,
        name_starts_with: str | None = None,
    ) -> dict[SongIdentity, tuple[SongTagAssignment, ...]]:
        """Return tags for many songs, grouped by domain song identity.

        Uses a single batch read for all supplied songs. When ``name_starts_with``
        is provided, only tags whose names start with that prefix are included.
        Empty mapping when no songs resolve or none have tags.
        """
        song_ids_by_identity = self._resolve_song_ids_map(songs)
        if not song_ids_by_identity:
            return {}
        rows = self._song_tag_repo.get_tags_for_songs_batch(
            list(song_ids_by_identity.values()),
            name_starts_with=name_starts_with,
        )
        song_by_id = {song_id: ident for ident, song_id in song_ids_by_identity.items()}
        grouped: dict[SongIdentity, list[SongTagAssignment]] = {ident: [] for ident in song_ids_by_identity}
        for row in rows:
            song_id = row.get("song_id")
            identity = song_by_id.get(song_id) if isinstance(song_id, int) else None
            if identity is None:
                continue
            grouped[identity].append(song_tag_assignment_from_batch_row(row, identity))
        return {ident: tuple(assignments) for ident, assignments in grouped.items()}

    def count_songs_by_tag(self, tag_key: str, target_value: str) -> int:
        """Count songs that have a tag with the given key and value."""
        return self._song_tag_repo.count_songs_by_tag(tag_key, target_value)

    def count_songs_by_numeric_tag(self, tag_key: str, target_value: float | str) -> int:
        """Count distinct songs with a numeric *tag_key* tag.

        Delegates to the uncapped ``COUNT(DISTINCT song_id)`` repository intent,
        which uses the same tag-key and safe-numeric predicate as the paged
        numeric search (no edge limit, no dependence on the paged query).
        """
        return self._song_tag_repo.count_songs_by_numeric_tag(tag_key, target_value)

    def find_songs_with_numeric_tag(
        self,
        identity: TagRef,
        *,
        limit: int | None,
        offset: int = 0,
    ) -> tuple[SongTagMatch, ...]:
        """Search songs with a numeric tag and return domain match objects."""
        rows = self._song_tag_repo.search_songs_by_numeric_tag(
            identity.name,
            str(identity.value),
            limit=limit,
            offset=offset,
        )
        return tuple(song_tag_match_from_row(row) for row in rows)

    def find_songs_with_tag(
        self,
        identity: TagRef,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[Song, ...]:
        """Search for domain songs with an exact tag key/value match."""
        return tuple(
            song_from_row(row)
            for row in self._song_tag_repo.search_songs_by_tag(
                identity.name,
                str(identity.value),
                limit=limit,
                offset=offset,
            )
        )

    def find_songs_with_tag_contains(
        self,
        identity: TagRef,
        *,
        limit: int | None = None,
    ) -> tuple[Song, ...]:
        """Return domain songs whose tag value contains ``identity.value`` (ILIKE substring)."""
        return tuple(
            song_from_row(row)
            for row in self._song_tag_repo.search_songs_by_tag_contains(
                identity.name,
                str(identity.value),
                limit=limit,
            )
        )

    def find_songs_with_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> tuple[Song, ...]:
        """Return domain songs whose tag value matches an ILIKE *pattern*."""
        return tuple(
            song_from_row(row)
            for row in self._song_tag_repo.search_songs_by_tag_pattern(tag_name, pattern, limit=limit)
        )

    # ------------------------------------------------------------------
    # Song-tag mutations
    # ------------------------------------------------------------------

    def replace_song_tags(
        self,
        song: SongIdentity,
        assignments: Sequence[SongTagAssignment],
    ) -> None:
        """Replace all tag associations for a song.

        Resolves tag natural keys set-based (no per-tag SQL loop) and delegates
        the delete-and-insert to the repository's short-owned transaction. A
        ``song`` that does not exist is a no-op.
        """
        song_id = self._resolve_song_id(song)
        if song_id is None:
            return
        tag_rows = [{"name": a.name, "value": str(a.value), "namespace": a.namespace} for a in assignments]
        tag_ids = self._tag_repo.get_or_create_tags_batch(tag_rows)
        edges = [
            {
                "song_id": song_id,
                "tag_id": tag_ids[(a.name, str(a.value), a.namespace)],
                "confidence": a.confidence,
                "source": a.source,
            }
            for a in assignments
        ]
        # Repo-owned short transaction: commits the pending tag inserts from
        # get_or_create_tags_batch together with the edge replacement.
        self._song_tag_repo.replace_song_tags(song_id, edges)

    def relink_tags(
        self,
        source: TagRef,
        target: TagRef,
        songs: Sequence[SongIdentity] | None = None,
    ) -> RelinkResult:
        """Remap song→tag edges from *source* to *target* (ADR-014 duplicate-safe).

        Source edges colliding with an existing target edge are dropped
        (``skipped``); the rest are re-pointed (``moved``). ``source_orphaned``
        reports whether the source tag lost all of its assignments. Returns a
        typed ``RelinkResult``; a source tag that does not exist yields
        ``RelinkResult(0, 0, 0)``.
        """
        source_ids = self._tag_repo.get_tag_ids_by_identities(
            [{"name": source.name, "value": str(source.value), "namespace": source.namespace}]
        )
        source_key = (source.name, str(source.value), source.namespace)
        source_id = source_ids.get(source_key)
        if source_id is None:
            return RelinkResult(moved=0, skipped=0, source_orphaned=0)
        target_ids = self._tag_repo.get_or_create_tags_batch(
            [{"name": target.name, "value": str(target.value), "namespace": target.namespace}]
        )
        target_id = target_ids[(target.name, str(target.value), target.namespace)]
        song_ids = self._resolve_song_ids(songs) if songs is not None else None
        counts = self._song_tag_repo.relink_song_tags(source_id, target_id, song_ids=song_ids)
        return RelinkResult(
            moved=counts["moved"],
            skipped=counts["skipped"],
            source_orphaned=counts["source_orphaned"],
        )

    def remove_song_tags(
        self,
        song: SongIdentity,
        identities: Sequence[TagRef] | None = None,
    ) -> None:
        """Remove tag edges for one song and run a DB-wide orphaned-tag cleanup.

        ``identities`` is optional: when ``None`` all tag edges for the song are
        removed. Resolves the identities set-based without creating tags.

        Side effect: after every per-song removal a DB-wide
        ``cleanup_orphaned_tags()`` is run to preserve provenance cleanup (tags
        that lost their last song assignment are deleted). This behavior is
        intentional and unchanged.
        """
        song_id = self._resolve_song_id(song)
        if song_id is None:
            return
        if identities is None:
            self._song_tag_repo.replace_song_tags(song_id, [])
        else:
            tag_ids = self._tag_repo.get_tag_ids_by_identities(
                [{"name": i.name, "value": str(i.value), "namespace": i.namespace} for i in identities]
            )
            resolved = [
                tag_ids[(i.name, str(i.value), i.namespace)]
                for i in identities
                if (i.name, str(i.value), i.namespace) in tag_ids
            ]
            if resolved:
                self._song_tag_repo.remove_tags_from_song(song_id, resolved)
        self._tag_repo.cleanup_orphaned_tags()

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        """Return value frequency distributions for the given tag names."""
        return self._tag_repo.get_tag_value_frequencies_batch(tag_names, limit=limit)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def count_orphaned_tags(self) -> int:
        """Count orphaned tags (no song assignment) without deleting any.

        Non-destructive read intent backing ``dry_run=True`` previews. Set-based
        over the persistence-private ``get_orphaned_tag_ids`` primitive; returns
        a plain scalar count (``0`` when none), never storage ids, rows, or edge
        dictionaries. No tag is deleted and no transaction context is exposed.
        """
        return len(self._tag_repo.get_orphaned_tag_ids())

    def admin_cleanup_orphaned_tags(self) -> TagCleanupResult:
        """Delete orphaned tags (no song assignment) and report the outcome.

        Sole destructive orphan-cleanup intent. Use ``count_orphaned_tags()``
        for a non-destructive preview.
        """
        orphaned_ids = self._tag_repo.get_orphaned_tag_ids()
        deleted = self._tag_repo.delete_tags_by_ids(orphaned_ids) if orphaned_ids else 0
        return TagCleanupResult(deleted=deleted, orphaned=len(orphaned_ids))

    def admin_truncate_tags(self) -> None:
        """Remove all tag rows."""
        return self._tag_repo.truncate_tags()

    def admin_truncate_song_tag_assignments(self) -> None:
        """Remove all song-to-tag assignment edges."""
        return self._song_tag_repo.truncate_song_tag_assignments()
