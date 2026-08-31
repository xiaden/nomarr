"""TagRepository — CRUD and domain queries for tags.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
JOINs, filtered queries, and batch operations.

Song-tag junction operations live in ``SongTagRepository``
(``song_tag_repo.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import TagRow
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session
    from sqlalchemy.schema import Table


def _escape_like_search(value: str) -> str:
    """Escape LIKE metacharacters in a literal search value."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_DEFAULT_NAMESPACE = "default"
# Removed ``tags`` metadata keys: accepted nowhere and rejected on write so a
# stale caller can never silently drop data intended for a non-identity column.
_REMOVED_TAG_METADATA_KEYS = frozenset({"source", "confidence", "tier", "created_at", "parent_tag_id"})


def _normalize_namespace(namespace: str | None) -> str:
    """Collapse an omitted/empty ordinary namespace to the literal ``default``.

    Real non-empty namespaces (e.g. ``nom``) are preserved verbatim; only the
    absent/empty ordinary case normalizes, so distinct namespaces are never
    silently collapsed onto one another.
    """
    return namespace or _DEFAULT_NAMESPACE


def _reject_removed_tag_metadata(payload: dict[str, Any]) -> None:
    """Reject write payload keys for removed ``tags`` metadata columns.

    ``tags`` is identity-only; silently ignoring a stale ``source`` /
    ``confidence`` / ``tier`` / ``created_at`` / ``parent_tag_id`` key would
    drop data the caller believed was persisted. Raise instead.
    """
    extra = _REMOVED_TAG_METADATA_KEYS.intersection(payload)
    if extra:
        raise ValueError("tags is identity-only; removed metadata keys not allowed: " + ", ".join(sorted(extra)))


_T: Table = Tag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_FT: Table = SongTag.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


def _tag_row_to_dto(row: Row) -> TagRow:
    """Convert a SQLAlchemy ``Row`` to an identity-only ``TagRow`` TypedDict."""
    m = row._mapping
    return TagRow(
        id=m["id"],
        namespace=m["namespace"],
        name=m["name"],
        value=m["value"],
    )


class TagRepository:
    """Repository for the ``tags`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── core CRUD ───────────────────────────────────────────────

    def get_tag(self, tag_id: int) -> TagRow | None:
        """Fetch a single tag by primary key."""
        with map_persistence_exceptions():
            row = select_by_key(_T, tag_id, session=self._session)
            return _tag_row_to_dto(row) if row else None

    def get_tags_by_ids(self, tag_ids: list[int]) -> list[TagRow]:
        """Fetch tags by their primary keys in one set-based query.

        Persistence-private primary-key batch read backing the root-database
        tag boundary resolver (P3 of TASK-song-intent-facade-correction-A) for
        callers that still receive an opaque external tag ID. Missing ids are
        simply absent from the result.
        """
        if not tag_ids:
            return []
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.id.in_(tag_ids))
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def get_tag_ids_by_identities(self, rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
        """Resolve ``(namespace, name, value)`` natural keys to tag IDs without creating.

        Set-based: one query for the whole batch. Missing keys are absent from
        the result (no tag creation) — safe for idempotent lookups such as tag
        removal or relink where silently creating a tag would be wrong.
        ``rows`` items use ``{"name": str, "value": str, "namespace": str}``.
        Returns ``{(namespace, name, value): tag_id}``.
        """
        if not rows:
            return {}
        conditions = [
            and_(
                _T.c.namespace == _normalize_namespace(r.get("namespace")),
                _T.c.name == r["name"],
                _T.c.value == str(r["value"]),
            )
            for r in rows
        ]
        stmt = select(_T.c.namespace, _T.c.name, _T.c.value, _T.c.id).where(or_(*conditions))
        result = self._session.execute(stmt)
        return {(row[0], row[1], row[2]): row[3] for row in result.all()}

    def get_or_create_tags_batch(self, rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], int]:
        """Set-based bulk get-or-create for tags keyed on ``(namespace, name, value)``.

        Deduplicates input rows by identity, resolves existing tags in ONE
        query, bulk-inserts the missing tags in ONE insert (conflict-safe), and
        re-reads any identity that lost an insert race.  Returns
        ``{(namespace, name, value): tag_id}``.

        UoW-safe: never commits internally — the caller's unit of work owns
        the transaction.  No per-tag loop on the hot path.

        Args:
            rows: Iterable of ``{"name": ..., "value": ..., "namespace": ...}``
                  dicts.  An omitted/empty ordinary ``namespace`` normalizes to
                  the literal ``"default"``.

        Returns:
            Mapping from ``(namespace, name, value)`` triple to tag id.

        """
        if not rows:
            return {}
        wanted: dict[tuple[str, str, str], dict[str, str]] = {}
        for r in rows:
            _reject_removed_tag_metadata(r)
            name = str(r["name"])
            value = str(r["value"])
            namespace = _normalize_namespace(r.get("namespace"))
            identity = (namespace, name, value)
            if identity not in wanted:
                wanted[identity] = {"namespace": namespace, "name": name, "value": value}

        identities = list(wanted)
        resolved: dict[tuple[str, str, str], int] = {}

        # 1) ONE query to resolve existing tags.
        conditions = [and_(_T.c.namespace == ns, _T.c.name == n, _T.c.value == v) for (ns, n, v) in identities]
        stmt = select(_T.c.namespace, _T.c.name, _T.c.value, _T.c.id).where(or_(*conditions))
        for row in self._session.execute(stmt):
            resolved[(row[0], row[1], row[2])] = int(row[3])

        # 2) ONE bulk insert for the missing tags (conflict-safe).
        missing = [wanted[i] for i in identities if i not in resolved]
        if missing:
            insert_stmt = (
                pg_insert(_T)
                .values(missing)
                .on_conflict_do_nothing(index_elements=[_T.c.namespace, _T.c.name, _T.c.value])
                .returning(_T.c.namespace, _T.c.name, _T.c.value, _T.c.id)
            )
            for row in self._session.execute(insert_stmt):
                resolved[(row[0], row[1], row[2])] = int(row[3])

        # 3) Re-read any identity that lost an insert race (conflict hit).
        unresolved = [i for i in identities if i not in resolved]
        if unresolved:
            conditions2 = [and_(_T.c.namespace == ns, _T.c.name == n, _T.c.value == v) for (ns, n, v) in unresolved]
            stmt2 = select(_T.c.namespace, _T.c.name, _T.c.value, _T.c.id).where(or_(*conditions2))
            for row in self._session.execute(stmt2):
                resolved[(row[0], row[1], row[2])] = int(row[3])

        return resolved

    def get_or_create_tag(self, name: str, value: str, namespace: str) -> int:
        """Return the id of an existing tag or insert a new one.

        ``name`` / ``value`` / ``namespace`` are the only accepted tag fields;
        the complete ``(namespace, name, value)`` identity is conflict-safe on
        insert and an empty/omitted ordinary namespace normalizes to
        ``"default"``.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                ns = _normalize_namespace(namespace)
                payload = {"namespace": ns, "name": name, "value": value}
                stmt = (
                    pg_insert(_T)
                    .values(**payload)
                    .on_conflict_do_nothing(index_elements=[_T.c.namespace, _T.c.name, _T.c.value])
                    .returning(_T.c.id)
                )
                inserted = self._session.execute(stmt).fetchone()
                if inserted is not None:
                    tag_id = int(inserted[0])
                else:
                    existing = self._session.execute(
                        select(_T.c.id).where(
                            _T.c.namespace == ns,
                            _T.c.name == name,
                            _T.c.value == value,
                        )
                    ).fetchone()
                    assert existing is not None
                    tag_id = int(existing[0])
            self._session.commit()
            return tag_id

    def create_tag(self, payload: dict[str, Any]) -> int:
        """Insert a new tag row and return its ``id``.

        Accepts only the identity fields ``name`` / ``value`` / ``namespace``
        (an omitted/empty ordinary namespace normalizes to ``"default"``);
        removed metadata keys are rejected.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                _reject_removed_tag_metadata(payload)
                row = insert_one(
                    _T,
                    {
                        "namespace": _normalize_namespace(payload.get("namespace")),
                        "name": str(payload["name"]),
                        "value": str(payload["value"]),
                    },
                    session=self._session,
                )
            self._session.commit()
            return int(row._mapping["id"])

    def delete_tag(self, tag_id: int) -> None:
        """Delete a tag by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_T, tag_id, session=self._session)
            self._session.commit()

    # ── orphan management ───────────────────────────────────────

    def get_orphaned_tag_ids(self) -> list[int]:
        """Return tag ids that have no song-tag assignments."""
        with map_persistence_exceptions():
            stmt = select(_T.c.id).outerjoin(_FT, _T.c.id == _FT.c.tag_id).where(_FT.c.id.is_(None))
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def cleanup_orphaned_tags(self) -> int:
        """Delete tags with no song assignments; return the count deleted."""
        with map_persistence_exceptions():
            orphaned = self.get_orphaned_tag_ids()
            if not orphaned:
                return 0
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.id.in_(orphaned))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    # ── tag listing ─────────────────────────────────────────────

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagRow]:
        """Return tags with optional name/value/search filters and pagination."""
        with map_persistence_exceptions():
            stmt = select(_T)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if value is not None:
                stmt = stmt.where(_T.c.value == value)
            if search is not None:
                escaped = _escape_like_search(search)
                stmt = stmt.where(_T.c.value.ilike(f"%{escaped}%", escape="\\"))
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_tag_row_to_dto(r) for r in result.all()]

    def count_tags(self) -> int:
        """Return total row count of ``tags``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    # ── search ──────────────────────────────────────────────────

    def get_tag_value_frequencies(
        self,
        tag_name: str,
        *,
        limit: int,
    ) -> list[tuple[str, str, int]]:
        """Return ``(namespace, value, count)`` triples for a given tag name.

        Groups by namespace as well as name/value so the same ``value`` under
        distinct namespaces is never collapsed. The result is namespace-bearing
        (private); a downstream projection may reduce it only at its documented
        boundary.
        """
        with map_persistence_exceptions():
            stmt = (
                select(_T.c.namespace, _T.c.value, func.count().label("cnt"))
                .where(_T.c.name == tag_name)
                .group_by(_T.c.namespace, _T.c.value)
                .order_by(func.count().desc())
                .limit(limit)
            )
            result = self._session.execute(stmt)
            return [(row[0], row[1], row[2]) for row in result.all()]

    def get_tag_value_frequencies_batch(
        self,
        tag_names: list[str],
        *,
        limit: int,
    ) -> dict[str, list[tuple[str, str, int]]]:
        """Return ``(namespace, value, count)`` triples for multiple tag names.

        Groups by ``(name, namespace, value)`` and returns a dict mapping each
        tag name to its list of ``(namespace, value, count)`` tuples, ordered by
        count descending. Namespace-bearing (private); a downstream projection
        may reduce it only at its documented boundary.
        """
        with map_persistence_exceptions():
            if not tag_names:
                return {}
            stmt = (
                select(_T.c.name, _T.c.namespace, _T.c.value, func.count().label("cnt"))
                .where(_T.c.name.in_(tag_names))
                .group_by(_T.c.name, _T.c.namespace, _T.c.value)
                .order_by(_T.c.name, func.count().desc())
            )
            result = self._session.execute(stmt)
            grouped: dict[str, list[tuple[str, str, int]]] = {name: [] for name in tag_names}
            for row in result.all():
                name, ns, value, cnt = row[0], row[1], row[2], row[3]
                if name in grouped:
                    grouped[name].append((ns, value, cnt))
            # Apply per-name limit (SQL LIMIT was global, not per-group)
            return {name: pairs[:limit] for name, pairs in grouped.items()}

    # ── Plan E facade support ───────────────────────────────────

    def list_all_tag_names(self, *, limit: int | None = None) -> list[str]:
        """Return distinct tag names."""
        with map_persistence_exceptions():
            stmt = select(_T.c.name).distinct()
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        """Count tags with optional name and search filters."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_T)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if search is not None:
                escaped_search = _escape_like_search(search)
                stmt = stmt.where(_T.c.value.ilike(f"%{escaped_search}%", escape="\\"))
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return tags (identity only) with their song-assignment count."""
        with map_persistence_exceptions():
            stmt = select(
                _T.c.id,
                _T.c.namespace,
                _T.c.name,
                _T.c.value,
                func.count(_FT.c.song_id).label("song_count"),
            ).outerjoin(_FT, _T.c.id == _FT.c.tag_id)
            if name is not None:
                stmt = stmt.where(_T.c.name == name)
            if search is not None:
                escaped_search = _escape_like_search(search)
                stmt = stmt.where(_T.c.value.ilike(f"%{escaped_search}%", escape="\\"))
            stmt = stmt.group_by(
                _T.c.id,
                _T.c.namespace,
                _T.c.name,
                _T.c.value,
            ).order_by(_T.c.id)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [
                {
                    "id": r[0],
                    "namespace": r[1],
                    "name": r[2],
                    "value": r[3],
                    "song_count": r[4],
                }
                for r in result.all()
            ]

    # ── maintenance ─────────────────────────────────────────────

    def truncate_tags(self) -> None:
        """Delete all rows from ``tags``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        """Delete tags by their primary keys; return the count deleted."""
        with map_persistence_exceptions():
            if not tag_ids:
                return 0
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.id.in_(tag_ids))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime
