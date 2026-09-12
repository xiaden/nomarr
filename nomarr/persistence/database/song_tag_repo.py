"""SongTagRepository — song ↔ tag junction operations.

Manages the ``song_tags`` junction table that links songs to tags.
Split from ``TagRepository`` to keep each repo focused on a single table
group (see persistence.md size guidelines).
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, and_, case, cast, delete, exists, func, literal, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from nomarr.helpers.dataclasses.song_tag_dataclass import MoodBatchResult
from nomarr.helpers.dto.repo_dto import NumericSongTagMatchRow, SongRow
from nomarr.helpers.exceptions import AmbiguousCommitError, DatabaseStateError, RetryableDatabaseError
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_mood_calibration_marker import SongMoodCalibrationMarker
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session
    from sqlalchemy.schema import Table

    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_tag_dataclass import MoodReplacementCommand
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.tag_repo import TagRepository


def _escape_like_search(value: str) -> str:
    """Escape LIKE metacharacters in a literal search value."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_T: Table = Tag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_ST: Table = SongTag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = Song.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_MM: Table = SongMoodCalibrationMarker.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table

#: Complete mood tier tag names owned by the repository (namespace ``nom``).
_MOOD_TAG_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
#: Bounded fresh-session attempts for immutable transient mood failures.
_MAX_MOOD_TRANSACTION_ATTEMPTS = 3


def _tag_row_to_dto(row: Row) -> dict[str, Any]:
    """Map a joined tag+song_tags row to identity fields plus edge metadata.

    Reads only identity columns from ``tags`` (id, namespace, name, value) and
    confidence/source/timestamps from the ``song_tags`` edge — never from the
    removed ``tags`` metadata columns.
    """
    m = row._mapping
    return {
        "id": m["id"],
        "namespace": m["namespace"],
        "name": m["name"],
        "value": m["value"],
        "confidence": m["confidence"],
        "source": m["source"],
        "created_at": m["created_at"],
    }


def _row_to_dto(row: Row) -> SongRow:
    """Convert a SQLAlchemy ``Row`` to a ``SongRow`` TypedDict."""
    m = row._mapping
    return SongRow(
        id=m["id"],
        library_id=m["library_id"],
        folder_id=m["folder_id"],
        path=m["path"],
        normalized_path=m["normalized_path"],
        file_size=m["file_size"],
        modified_time=m["modified_time"],
        duration_seconds=m["duration_seconds"],
        chromaprint=m["chromaprint"],
        needs_tagging=m["needs_tagging"],
        is_valid=m["is_valid"],
        tagged=m["tagged"],
        calibration_hash=m["calibration_hash"],
        write_claimed_by=m["write_claimed_by"],
        last_tagged_at=m["last_tagged_at"],
        scanned_at=m["scanned_at"],
        created_at=m["created_at"],
    )


def _numeric_match_row_to_dto(row: Row) -> NumericSongTagMatchRow:
    """Convert a SQLAlchemy ``Row`` to a ``NumericSongTagMatchRow`` TypedDict."""
    m = row._mapping
    return NumericSongTagMatchRow(
        id=m["id"],
        library_id=m["library_id"],
        folder_id=m["folder_id"],
        path=m["path"],
        normalized_path=m["normalized_path"],
        file_size=m["file_size"],
        modified_time=m["modified_time"],
        duration_seconds=m["duration_seconds"],
        chromaprint=m["chromaprint"],
        needs_tagging=m["needs_tagging"],
        is_valid=m["is_valid"],
        tagged=m["tagged"],
        calibration_hash=m["calibration_hash"],
        write_claimed_by=m["write_claimed_by"],
        last_tagged_at=m["last_tagged_at"],
        scanned_at=m["scanned_at"],
        created_at=m["created_at"],
        matched_tag=m["matched_tag"],
        distance=m["distance"],
    )


#: Regex for a numeric text value: optional sign, int/decimal, optional exponent.
#: Mirrors the acceptance rules of ``is_numeric_tag_value`` (int/float, non-bool)
#: as applied to string-typed ``tags.value``.
_NUMERIC_TEXT_RE = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$"


class SongTagRepository:
    """Repository for the ``song_tags`` junction table."""

    def __init__(
        self,
        session: scoped_session[Session],
        *,
        tag_repo: TagRepository | None = None,
        song_repo: SongRepository | None = None,
        library_repo: LibraryRepository | None = None,
    ) -> None:
        self._session = session
        # Collaborators required only by the locator-addressed mood intent. They
        # are wired by ``Database``; other repository methods do not need them.
        self._tag_repo = tag_repo
        self._song_repo = song_repo
        self._library_repo = library_repo

    # ── song-tag associations ───────────────────────────────────

    def get_tags_for_song(self, song_id: int) -> list[dict[str, Any]]:
        """Return all tags assigned to a song via the ``song_tags`` junction.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``.
        """
        with map_persistence_exceptions():
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id == song_id)
            )
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def assign_tag_to_song(
        self,
        song_id: int,
        tag_id: int,
        confidence: float = 1.0,
        source: str | None = None,
    ) -> None:
        """Insert a row into ``song_tags`` linking *song_id* to *tag_id*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                payload = {
                    "song_id": song_id,
                    "tag_id": tag_id,
                    "confidence": confidence,
                    "source": source or "nomarr",
                    "created_at": int(time.time() * 1000),
                }
                insert_one(_ST, payload, session=self._session)
            self._session.commit()

    def remove_tag_from_song(self, song_id: int, tag_id: int) -> None:
        """Delete the junction row for a specific song + tag pair."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_ST).where(
                    _ST.c.song_id == song_id,
                    _ST.c.tag_id == tag_id,
                )
                self._session.execute(stmt)
            self._session.commit()

    def remove_tags_from_song(self, song_id: int, tag_ids: list[int]) -> None:
        """Delete several tag assignments for a song in one transaction."""
        if not tag_ids:
            return
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_ST).where(
                    _ST.c.song_id == song_id,
                    _ST.c.tag_id.in_(tag_ids),
                )
                self._session.execute(stmt)
            self._session.commit()

    def replace_song_tags_batch(
        self,
        edges: list[dict[str, Any]],
        *,
        song_ids: list[int] | None = None,
    ) -> None:
        """Set-based full-replace of song↔tag edges across many songs.

        Takes *edges* as a flat list of ``{"song_id", "tag_id",
        "confidence", "source"}`` dicts (callers MUST resolve ``tag_id``
        beforehand — this repo never looks tags up by name/value).  For every
        affected song the existing edges are deleted and the supplied edges are
        bulk-inserted in ONE statement each (full-replace semantics, so a retry
        yields the same assignments).  ``song_ids`` identifies affected songs
        when the replacement is intentionally empty.  Input rows are
        deduplicated by ``(song_id, tag_id)``.

        UoW-safe: never commits internally — the caller's unit of work owns
        the transaction.  No per-song/per-tag loop on the hot path.

        Args:
            edges: Flat list of edge dicts.  ``confidence`` defaults to
                   ``1.0`` and ``source`` to ``"nomarr"`` when omitted.

        """
        affected_song_ids = list(dict.fromkeys(song_ids or [int(e["song_id"]) for e in edges]))
        if not affected_song_ids:
            return
        now_ms = int(time.time() * 1000)
        # Dedupe by (song_id, tag_id) and group per song.
        deduped: dict[tuple[int, int], dict[str, Any]] = {}
        for e in edges:
            key = (int(e["song_id"]), int(e["tag_id"]))
            deduped.setdefault(
                key,
                {
                    "song_id": key[0],
                    "tag_id": key[1],
                    "confidence": float(e.get("confidence", 1.0)),
                    "source": str(e.get("source", "nomarr")),
                    "created_at": now_ms,
                },
            )
        rows = list(deduped.values())
        self._session.execute(delete(_ST).where(_ST.c.song_id.in_(affected_song_ids)))
        if rows:
            self._session.execute(pg_insert(_ST).values(rows))

    def replace_song_tags(self, song_id: int, tags: list[dict[str, Any]]) -> None:
        """Delete all existing tag assignments for a song and insert new ones."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_ST).where(_ST.c.song_id == song_id))
                if tags:
                    now_ms = int(time.time() * 1000)
                    rows = [
                        {
                            "song_id": song_id,
                            "tag_id": t["tag_id"],
                            "confidence": t.get("confidence", 1.0),
                            "source": t.get("source", "nomarr"),
                            "created_at": now_ms,
                        }
                        for t in tags
                    ]
                    self._session.execute(pg_insert(_ST).values(rows))
            self._session.commit()

    # ── dedicated mood replacement (owner transaction) ──────────

    def replace_mood_tags_batch(
        self,
        commands: Sequence[MoodReplacementCommand],
    ) -> MoodBatchResult:
        """Apply a bounded, locator-addressed, all-or-none mood publication.

        The Tier-3 facade has already validated and de-duplicated *commands*;
        this repository intent owns the complete short transaction: private
        ``SongIdentity`` resolution, complete tag-identity creation, mood-edge
        and marker SQL, one commit, rollback on failure, poisoned-session
        disposal, and a bounded fresh-session replay of the immutable command
        set for the retryable SQLSTATEs. Transient serialization/deadlock
        failures retry the whole immutable command set; every other failure is
        a redacted infrastructure outcome and never a locator miss.
        """
        for attempt in range(_MAX_MOOD_TRANSACTION_ATTEMPTS):
            try:
                return self._replace_mood_batch_once(commands)
            except RetryableDatabaseError:
                self._discard_session()
                if attempt == _MAX_MOOD_TRANSACTION_ATTEMPTS - 1:
                    return MoodBatchResult("INFRA_FAILURE", len(commands))
            except AmbiguousCommitError:
                self._discard_session()
                return MoodBatchResult("AMBIGUOUS_COMMIT", len(commands))
            except Exception:
                self._discard_session()
                return MoodBatchResult("INFRA_FAILURE", len(commands))
        return MoodBatchResult("INFRA_FAILURE", len(commands))

    def _replace_mood_batch_once(
        self,
        commands: Sequence[MoodReplacementCommand],
    ) -> MoodBatchResult:
        """Run one complete mood replacement unit of work and commit it once.

        Composes only UoW-safe existing primitives
        (``TagRepository.get_or_create_tags_batch`` and set-based reads, which
        never commit) so tag creation, mood edges, and the marker publish in a
        single owner transaction. All locator resolution and SQL run before the
        distinct commit phase in :meth:`_commit_mood_batch`.

        Same-locator single-winner invariant (D2R-A): immediately after private
        ``SongIdentity`` resolution this method locks every resolved private
        ``songs`` row with ``SELECT ... FOR NO KEY UPDATE`` (see
        :meth:`_lock_mood_song_rows`) before any mood/marker read. A later
        replacement for the same ``SongIdentity`` therefore blocks until the
        predecessor's owner transaction commits and then reads post-commit
        state: concurrent same-locator replacements cannot interleave or union.
        Batch locks are acquired all-or-none in ascending private-id order, so
        concurrent batches take the same lock order and cannot deadlock. This
        is the only serialization mechanism -- there is no lock table, marker
        lock, advisory lock, OCC/revision, idempotency registry, or publication
        envelope. The lock is pre-commit, so a serialization/deadlock raised by
        it is classified through the existing retryable path and never through
        the commit phase.
        """
        if self._tag_repo is None or self._song_repo is None or self._library_repo is None:
            raise RuntimeError("SongTagRepository mood resolvers are not wired")
        now_ms = int(time.time() * 1000)
        with map_persistence_exceptions():
            identities = tuple(command.song for command in commands)
            song_ids = self._resolve_mood_song_ids_map(identities)
            if len(song_ids) != len(identities):
                # A stale/delete-recreate locator is a typed miss: no mutation,
                # no generated id, and never an alias/tombstone/history lookup.
                self._session.rollback()
                return MoodBatchResult("MISSING_LOCATOR", len(commands))

            scope_song_ids = list(song_ids.values())
            self._lock_mood_song_rows(scope_song_ids)
            desired_by_song: dict[int, set[tuple[str, str, str]]] = {}
            tag_rows: list[dict[str, str]] = []
            for command in commands:
                song_id = song_ids[command.song]
                desired: set[tuple[str, str, str]] = set()
                if command.assignments is not None:
                    for tier, values in command.assignments.tiers:
                        for value in values:
                            desired.add(("nom", tier, value))
                            tag_rows.append({"namespace": "nom", "name": tier, "value": value})
                desired_by_song[song_id] = desired

            tag_ids = self._tag_repo.get_or_create_tags_batch(tag_rows)
            existing = self._session.execute(
                select(
                    _ST.c.song_id,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.tag_id,
                )
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _ST.c.song_id.in_(scope_song_ids),
                    _T.c.namespace == "nom",
                    _T.c.name.in_(_MOOD_TAG_NAMES),
                )
            ).all()
            existing_by_song: dict[int, dict[tuple[str, str, str], int]] = {sid: {} for sid in scope_song_ids}
            for row in existing:
                existing_by_song[int(row[0])][("nom", row[1], row[2])] = int(row[3])

            obsolete_pairs: list[tuple[int, int]] = []
            insert_rows: list[dict[str, Any]] = []
            changed_by_song: dict[int, bool] = dict.fromkeys(scope_song_ids, False)
            for command in commands:
                song_id = song_ids[command.song]
                current = existing_by_song[song_id]
                desired = desired_by_song[song_id]
                obsolete = set(current) - desired
                missing = desired - set(current)
                if obsolete or missing:
                    changed_by_song[song_id] = True
                obsolete_pairs.extend((song_id, current[key]) for key in obsolete)
                insert_rows.extend(
                    {
                        "song_id": song_id,
                        "tag_id": tag_ids[key],
                        "confidence": 1.0,
                        "source": "nomarr",
                        "created_at": now_ms,
                    }
                    for key in missing
                )

            existing_markers = {
                int(row[0]): row[1]
                for row in self._session.execute(
                    select(_MM.c.song_id, _MM.c.calibration_version).where(_MM.c.song_id.in_(scope_song_ids))
                ).all()
            }
            marker_upsert_rows: list[dict[str, Any]] = []
            marker_delete_ids: list[int] = []
            for command in commands:
                song_id = song_ids[command.song]
                wanted = command.marker.version if command.marker.status == "calibrated" else None
                if existing_markers.get(song_id) != wanted:
                    changed_by_song[song_id] = True
                    if wanted is None:
                        marker_delete_ids.append(song_id)
                    else:
                        marker_upsert_rows.append({"song_id": song_id, "calibration_version": wanted})

            if obsolete_pairs:
                self._session.execute(delete(_ST).where(tuple_(_ST.c.song_id, _ST.c.tag_id).in_(obsolete_pairs)))
            if insert_rows:
                self._session.execute(pg_insert(_ST).values(insert_rows))
            if marker_delete_ids:
                self._session.execute(delete(_MM).where(_MM.c.song_id.in_(marker_delete_ids)))
            if marker_upsert_rows:
                upsert = pg_insert(_MM).values(marker_upsert_rows)
                self._session.execute(
                    upsert.on_conflict_do_update(
                        index_elements=[_MM.c.song_id],
                        set_={"calibration_version": upsert.excluded.calibration_version},
                    )
                )

            changed_count = sum(1 for changed in changed_by_song.values() if changed)
        # Commit is a distinct transaction phase: a commit-time failure with an
        # unknown outcome must never be reported as plain infrastructure or
        # blindly retried.
        self._commit_mood_batch()
        if changed_count:
            return MoodBatchResult("UPDATED", len(commands), changed_count)
        return MoodBatchResult("UNCHANGED", len(commands))

    def _lock_mood_song_rows(self, song_ids: Sequence[int]) -> None:
        """Serialize same-locator mood replacements with private row locks.

        Locks every resolved private ``songs`` row in the caller's single owner
        transaction with ``SELECT ... FOR NO KEY UPDATE`` before any mood/marker
        read. ``FOR NO KEY UPDATE`` self-conflicts, so two same-locator
        replacements serialize, but it does not conflict with the ``FOR KEY
        SHARE`` lock a foreign-key insert acquires on the song row -- literal
        ``FOR UPDATE`` would block ordinary ``song_tags`` inserts and regress
        existing duplicate-edge negative behavior, so the non-key row lock is
        the minimal correct choice. Handles are locked in ascending order in
        ONE statement per batch, so concurrent batches acquire locks in the same
        order (all-or-none, deadlock-avoiding) and a later same-``SongIdentity``
        replacement blocks until the predecessor commits, then reads the
        committed state rather than a pre-commit snapshot -- no interleave, no
        union. Uses row locks only: no lock table, marker lock, advisory lock,
        OCC/revision, idempotency registry, or publication envelope. The private
        row handles never leave this method or the repository.
        """
        if not song_ids:
            return
        self._session.execute(
            select(_S.c.id).where(_S.c.id.in_(sorted(song_ids))).order_by(_S.c.id).with_for_update(key_share=True)
        )

    def _resolve_mood_song_ids_map(self, songs: Sequence[SongIdentity]) -> dict[SongIdentity, int]:
        """Resolve song locators to private storage ids, keyed by identity.

        Set-based: libraries resolve by ``library_uuid`` in one query and songs
        in one query. Integer ids never leave the repository.
        """
        assert self._library_repo is not None
        assert self._song_repo is not None
        if not songs:
            return {}
        library_uuid_map = self._library_repo.get_library_ids_by_uuids(list({s.library.library_uuid for s in songs}))
        resolved = [s for s in songs if s.library.library_uuid in library_uuid_map]
        song_id_map = self._song_repo.get_song_ids_by_normalized_paths(
            [(library_uuid_map[s.library.library_uuid], s.normalized_path) for s in resolved]
        )
        return {
            s: song_id_map[(library_uuid_map[s.library.library_uuid], s.normalized_path)]
            for s in resolved
            if (library_uuid_map[s.library.library_uuid], s.normalized_path) in song_id_map
        }

    def _commit_mood_batch(self) -> None:
        """Commit the owner transaction and classify commit-phase failures.

        A ``40003`` (statement/transaction completion unknown) or a pgcode-less
        ``OperationalError`` / ``InterfaceError`` / generic ``DBAPIError`` raised
        during or after ``commit()`` means the commit outcome is unknown: the
        session is discarded by the caller and the result is
        ``AMBIGUOUS_COMMIT`` -- never a success claim and never a blind retry.
        The retryable serialization/deadlock SQLSTATEs remain bounded
        fresh-session retries; every other commit failure is a redacted
        ``INFRA_FAILURE``.

        This transaction-phase distinction is deliberately owned here. The
        global ``map_persistence_exceptions`` mapper is intentionally unchanged,
        so a pgcode-less failure outside the commit path stays ``INFRA_FAILURE``
        rather than being misclassified as an ambiguous commit.
        """
        try:
            self._session.commit()
        except Exception as exc:
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode in {"40001", "40P01", "55P03"}:
                raise RetryableDatabaseError("Database retryable commit failure") from None
            if pgcode == "40003" or (pgcode is None and isinstance(exc, DBAPIError)):
                raise AmbiguousCommitError("Database commit outcome is unknown") from None
            raise DatabaseStateError("Database commit failed") from None

    def _discard_session(self) -> None:
        """Roll back and dispose the current session so a retry starts fresh."""
        with contextlib.suppress(Exception):
            self._session.rollback()
        with contextlib.suppress(Exception):
            self._session.remove()

    def get_songs_for_tag(self, tag_id: int, limit: int | None = None) -> list[SongRow]:
        """Return songs assigned to a tag via JOIN."""
        with map_persistence_exceptions():
            stmt = select(_S).join(_ST, _S.c.id == _ST.c.song_id).where(_ST.c.tag_id == tag_id)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def list_song_ids_for_tag(
        self,
        tag_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[int]:
        """Return song ids assigned to a tag with pagination, ordered by song id."""
        with map_persistence_exceptions():
            stmt = select(_ST.c.song_id).where(_ST.c.tag_id == tag_id).order_by(_ST.c.song_id)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    # ── batch queries ───────────────────────────────────────────

    def get_tags_for_songs_batch(
        self,
        song_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return tag assignments for a batch of song ids.

        Each dict contains ``song_id``, ``tag_id``, ``tag_name``,
        ``tag_value``, ``namespace``, and the edge metadata ``confidence`` and
        ``source`` (from ``song_tags`` only).
        """
        with map_persistence_exceptions():
            if not song_ids:
                return []
            stmt = (
                select(
                    _ST.c.song_id,
                    _ST.c.tag_id,
                    _T.c.name,
                    _T.c.value,
                    _T.c.namespace,
                    _ST.c.confidence,
                    _ST.c.source,
                )
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id.in_(song_ids))
            )
            if name_starts_with is not None:
                stmt = stmt.where(_T.c.name.like(name_starts_with + "%"))
            result = self._session.execute(stmt)
            return [
                {
                    "song_id": r[0],
                    "tag_id": r[1],
                    "tag_name": r[2],
                    "tag_value": r[3],
                    "namespace": r[4],
                    "confidence": r[5],
                    "source": r[6],
                }
                for r in result.all()
            ]

    def get_song_tags(self, song_id: int, nomarr_only: bool = False) -> list[dict[str, Any]]:
        """Return tags for a song, optionally filtered to ``nom:`` namespace.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``.
        """
        with map_persistence_exceptions():
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(_ST.c.song_id == song_id)
            )
            if nomarr_only:
                stmt = stmt.where(_T.c.namespace == "nom")
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── search ──────────────────────────────────────────────────

    # ── numeric tag search ─────────────────────────────────────

    @staticmethod
    def _guarded_numeric_value(value_col: Any, dialect_name: str):
        """Return a SQL expression yielding the numeric value of *value_col* or NULL.

        The CASE guard ensures invalid numeric text in ``tags.value`` can NEVER
        reach an unconditional ``CAST`` that raises: PostgreSQL's
        ``CAST(text AS float)`` aborts the whole statement on bad input, so the
        guard is essential there. SQLite's ``CAST`` never raises, but the same
        guard stops non-numeric strings (e.g. ``"rock"``) from being coerced to
        ``0.0`` and matching a bogus zero distance. The dialect-specific
        regexp operator (``~`` on PostgreSQL, a GLOB character-class check on
        SQLite) is selected here so the validity predicate stays explicit.
        """
        if dialect_name == "postgresql":
            is_numeric = value_col.op("~")(_NUMERIC_TEXT_RE)
        else:
            # SQLite has no built-in regexp(); a GLOB character-class check is
            # sufficient for the integer/decimal values in practice and rejects
            # non-numeric text. Slightly more permissive than the PostgreSQL
            # regex (e.g. "1.2.3") — acceptable and covered by query-shape tests.
            is_numeric = and_(
                value_col.op("GLOB")("*[0-9]*"),
                ~value_col.op("GLOB")("*[^0-9.eE+-]*"),
            )
        return case((is_numeric, cast(value_col, Float)), else_=None)

    def search_songs_by_numeric_tag(
        self,
        tag_key: str,
        target_value: float | str,
        *,
        namespace: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[NumericSongTagMatchRow]:
        """Return songs with a numeric *tag_key* tag, ordered by tag distance.

        A set-based query over ``_S``/``_ST``/``_T`` keeps only tags whose
        ``name`` is *tag_key* and whose ``value`` is valid numeric text, picks
        the single closest tag per song (deterministic tie-break by tag id),
        orders the result by ``distance ASC, song id ASC``, and applies
        offset/limit in SQL before any rows are materialized in Python.
        """
        with map_persistence_exceptions():
            bind = getattr(self._session, "bind", None)
            dialect = getattr(bind, "dialect", None)
            dialect_name = dialect.name if dialect is not None else "postgresql"

            numeric_value = self._guarded_numeric_value(_T.c.value, dialect_name)
            numeric_target = literal(float(target_value))
            distance = func.abs(numeric_value - numeric_target)
            row_number = (
                func.row_number()
                .over(
                    partition_by=_ST.c.song_id,
                    order_by=(distance.asc(), _T.c.id.asc()),
                )
                .label("rn")
            )

            inner = (
                select(
                    _S,
                    _T.c.value.label("matched_tag"),
                    distance.label("distance"),
                    row_number,
                )
                .select_from(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.namespace == namespace,
                    _T.c.name == tag_key,
                    distance.is_not(None),
                )
                .subquery()
            )

            stmt = select(inner).where(inner.c.rn == 1).order_by(inner.c.distance.asc(), inner.c.id.asc())
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_numeric_match_row_to_dto(r) for r in result.all()]

    def count_songs_by_numeric_tag(self, tag_key: str, target_value: float | str, *, namespace: str) -> int:
        """Count distinct songs matching a numeric *tag_key* tag in *namespace*.

        Separate uncapped query using the SAME tag-key, namespace, and
        safe-numeric predicate as :meth:`search_songs_by_numeric_tag` — no edge
        limit and no dependence on the paged query.
        """
        with map_persistence_exceptions():
            bind = getattr(self._session, "bind", None)
            dialect = getattr(bind, "dialect", None)
            dialect_name = dialect.name if dialect is not None else "postgresql"

            numeric_value = self._guarded_numeric_value(_T.c.value, dialect_name)
            distance = func.abs(numeric_value - literal(float(target_value)))
            stmt = (
                select(func.count(func.distinct(_ST.c.song_id)))
                .select_from(_ST)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.namespace == namespace,
                    _T.c.name == tag_key,
                    distance.is_not(None),
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def search_songs_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        namespace: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SongRow]:
        """Return songs that have a tag with exact *tag_key* name and *value* in *namespace*."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(_T.c.namespace == namespace, _T.c.name == tag_key, _T.c.value == value)
            )
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def search_songs_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        namespace: str,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return songs whose tag value contains *value* (ILIKE) in *namespace*."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.namespace == namespace,
                    _T.c.name == tag_key,
                    _T.c.value.ilike(f"%{_escape_like_search(value)}%", escape="\\"),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def search_songs_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        namespace: str,
        limit: int | None = None,
    ) -> list[SongRow]:
        """Return songs whose tag value matches an ILIKE *pattern* in *namespace*."""
        with map_persistence_exceptions():
            stmt = (
                select(_S)
                .join(_ST, _S.c.id == _ST.c.song_id)
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.namespace == namespace,
                    _T.c.name == tag_name,
                    _T.c.value.ilike(pattern),
                )
            )
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def relink_song_tags(
        self,
        source_tag_id: int,
        target_tag_id: int,
        *,
        song_ids: list[int] | None = None,
    ) -> dict[str, int]:
        """Re-point assignments, removing collisions; return moved/skipped counts.

        ADR-014 duplicate-safe relink: source rows that would collide with an
        existing target row are deleted (``skipped``) before the remaining
        source rows are re-pointed to the target (``moved``). ``source_orphaned``
        is 1 when the source tag lost all of its assignments as a result of this
        operation (and was not already orphaned), else 0.

        The whole operation runs in one short repository-owned transaction.
        Returns ``{"moved": int, "skipped": int, "source_orphaned": int}``.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                target_edges = _ST.alias("target_song_tags")

                in_scope = [_ST.c.tag_id == source_tag_id]
                if song_ids is not None:
                    in_scope.append(_ST.c.song_id.in_(song_ids))

                source_total = (
                    self._session.execute(select(func.count()).select_from(_ST).where(*in_scope)).scalar() or 0
                )

                collision = exists(
                    select(1)
                    .select_from(target_edges)
                    .where(
                        target_edges.c.song_id == _ST.c.song_id,
                        target_edges.c.tag_id == target_tag_id,
                    )
                )
                skipped = (
                    self._session.execute(
                        select(func.count()).select_from(_ST).where(*in_scope).where(collision)
                    ).scalar()
                    or 0
                )

                # Remove source rows that would collide with an existing target
                # row before moving the remaining source rows.  Merely excluding
                # those rows from UPDATE leaves the source assignment behind.
                delete_stmt = delete(_ST).where(*in_scope).where(collision)
                self._session.execute(delete_stmt)

                update_stmt = update(_ST).where(*in_scope).values(tag_id=target_tag_id)
                self._session.execute(update_stmt)

                remaining = (
                    self._session.execute(
                        select(func.count()).select_from(_ST).where(_ST.c.tag_id == source_tag_id)
                    ).scalar()
                    or 0
                )
            self._session.commit()
            source_orphaned = 1 if remaining == 0 and source_total > 0 else 0
            return {
                "moved": int(source_total - skipped),
                "skipped": int(skipped),
                "source_orphaned": int(source_orphaned),
            }

    # ── Plan E facade support ───────────────────────────────────

    def get_genre_tags_for_songs(self, song_ids: list[int], *, namespace: str = "default") -> list[dict[str, Any]]:
        """Return genre tags assigned to the given song ids.

        Each row carries identity fields from ``tags`` plus edge metadata
        (confidence, source, created_at) from ``song_tags``. Genre is an
        ordinary tag, so the query is constrained to *namespace* (``default``
        for ordinary genre tags).
        """
        with map_persistence_exceptions():
            if not song_ids:
                return []
            stmt = (
                select(
                    _T.c.id,
                    _T.c.namespace,
                    _T.c.name,
                    _T.c.value,
                    _ST.c.confidence,
                    _ST.c.source,
                    _ST.c.created_at,
                )
                .join(_ST, _T.c.id == _ST.c.tag_id)
                .where(
                    _ST.c.song_id.in_(song_ids),
                    _T.c.name == "genre",
                    _T.c.namespace == namespace,
                )
            )
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    # ── maintenance ─────────────────────────────────────────────

    def truncate_song_tag_assignments(self) -> None:
        """Delete all rows from ``song_tags``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_ST))
            self._session.commit()

    def count_songs_for_tag(self, tag_id: int) -> int:
        """Count song-tag assignments for a specific tag."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_ST).where(_ST.c.tag_id == tag_id)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def count_songs_by_tag(self, tag_key: str, target_value: str, *, namespace: str) -> int:
        """Count distinct songs assigned to tags matching *tag_key*, *target_value*, and *namespace*."""
        with map_persistence_exceptions():
            stmt = (
                select(func.count(func.distinct(_ST.c.song_id)))
                .join(_T, _T.c.id == _ST.c.tag_id)
                .where(
                    _T.c.namespace == namespace,
                    _T.c.name == tag_key,
                    _T.c.value == target_value,
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def get_song_tag_edges_for_tags(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return song-tag edge rows for the given tag ids.

        Each dict contains ``song_id``, ``tag_id``, ``confidence``, and ``source``.
        """
        with map_persistence_exceptions():
            if not tag_ids:
                return []
            stmt = select(
                _ST.c.song_id,
                _ST.c.tag_id,
                _ST.c.confidence,
                _ST.c.source,
            ).where(_ST.c.tag_id.in_(tag_ids))
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [
                {
                    "song_id": r[0],
                    "tag_id": r[1],
                    "confidence": r[2],
                    "source": r[3],
                }
                for r in result.all()
            ]
