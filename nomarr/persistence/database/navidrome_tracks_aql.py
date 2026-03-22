"""Navidrome tracks and file-link operations for ArangoDB.

Manages ``navidrome_tracks`` vertex collection (keyed by Navidrome song ID) and
``has_nd_id`` edge collection linking tracks to ``library_files`` documents.

Collection schemas:
    navidrome_tracks:  {_key: nd_id}
    has_nd_id:         {_from: "navidrome_tracks/{nd_id}", _to: "library_files/{file_key}"}
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

_TRACKS = "navidrome_tracks"
_HAS_ND_ID = "has_nd_id"


class NavidromeTracksOperations:
    """CRUD operations for navidrome_tracks vertices and has_nd_id edges."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db

    # ── Vertex operations ────────────────────────────────────────────

    def upsert_track(self, nd_id: str) -> None:
        """Ensure a navidrome_tracks vertex exists for *nd_id*.

        Uses AQL UPSERT so repeated calls are idempotent.
        """
        query = """
        UPSERT { _key: @nd_id }
        INSERT { _key: @nd_id }
        UPDATE {}
        IN @@collection
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"nd_id": nd_id, "@collection": _TRACKS},
        )
        cursor.close(ignore_missing=True)

    def bulk_upsert_tracks(self, nd_ids: list[str]) -> int:
        """Ensure vertices exist for all *nd_ids*.

        Returns:
            Number of documents upserted.
        """
        if not nd_ids:
            return 0

        docs = [{"_key": nd_id} for nd_id in nd_ids]
        query = """
        FOR doc IN @docs
            UPSERT { _key: doc._key }
            INSERT doc
            UPDATE {}
            IN @@collection
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"docs": docs, "@collection": _TRACKS},  # type: ignore[dict-item]  # python-arango stubs don't accept list[dict] as bind_vars
        )
        cursor.close(ignore_missing=True)
        return len(nd_ids)

    def get_all_track_keys(self) -> list[str]:
        """Return all ``_key`` values from navidrome_tracks."""
        query = """
        FOR doc IN @@collection
            RETURN doc._key
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"@collection": _TRACKS},
        )
        result: list[str] = list(cursor)
        cursor.close(ignore_missing=True)
        return result

    def delete_tracks_cascade(self, nd_ids: list[str]) -> int:
        """Delete tracks and all connected edges (has_nd_id and has_plays).

        Uses AQL to remove edges first, then vertices.  Returns the number
        of vertex documents removed.
        """
        if not nd_ids:
            return 0

        full_ids = [f"{_TRACKS}/{nd_id}" for nd_id in nd_ids]

        # Remove has_nd_id edges where _from matches
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN @@edge_collection
                FILTER edge._from IN @full_ids
                REMOVE edge IN @@edge_collection
            """,
            bind_vars={"full_ids": full_ids, "@edge_collection": _HAS_ND_ID},
        )

        # Remove has_plays edges where _to matches (inbound from playcounts)
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN @@edge_collection
                FILTER edge._to IN @full_ids
                REMOVE edge IN @@edge_collection
            """,
            bind_vars={"full_ids": full_ids, "@edge_collection": "has_plays"},
        )

        # Remove track vertices
        query = """
        FOR nd_id IN @nd_ids
            REMOVE { _key: nd_id } IN @@collection
            OPTIONS { ignoreErrors: true }
        RETURN 1
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"nd_ids": nd_ids, "@collection": _TRACKS},
        )
        count = sum(1 for _ in cursor)
        cursor.close(ignore_missing=True)
        return count

    # ── Edge operations (has_nd_id) ──────────────────────────────────

    def ensure_file_link(self, nd_id: str, file_id: str) -> None:
        """Ensure an edge from ``navidrome_tracks/{nd_id}`` to *file_id* exists.

        *file_id* must be a full document ID (e.g. ``library_files/abc123``).
        Uses UPSERT on ``(_from, _to)`` for idempotency.
        """
        from_id = f"{_TRACKS}/{nd_id}"
        query = """
        UPSERT { _from: @from_id, _to: @to_id }
        INSERT { _from: @from_id, _to: @to_id }
        UPDATE {}
        IN @@collection
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"from_id": from_id, "to_id": file_id, "@collection": _HAS_ND_ID},
        )
        cursor.close(ignore_missing=True)

    def bulk_ensure_file_links(self, mappings: list[dict[str, str]]) -> int:
        """Ensure edges exist for a batch of nd_id→file_id mappings.

        Each mapping dict must have ``nd_id`` and ``file_id`` keys.
        ``file_id`` must be a full document ID.

        Returns:
            Number of edges upserted.
        """
        if not mappings:
            return 0

        edges = [
            {"_from": f"{_TRACKS}/{m['nd_id']}", "_to": m["file_id"]}
            for m in mappings
        ]
        query = """
        FOR edge IN @edges
            UPSERT { _from: edge._from, _to: edge._to }
            INSERT edge
            UPDATE {}
            IN @@collection
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"edges": edges, "@collection": _HAS_ND_ID},  # type: ignore[dict-item]  # python-arango stubs don't accept list[dict] as bind_vars
        )
        cursor.close(ignore_missing=True)
        return len(mappings)

    # ── Resolution queries ───────────────────────────────────────────

    def resolve_nd_to_file(self, nd_id: str) -> str | None:
        """Resolve a Navidrome track ID to a Nomarr file document ID.

        Traverses the ``has_nd_id`` edge from ``navidrome_tracks/{nd_id}``.

        Returns:
            Full document ID (e.g. ``library_files/abc123``) or None.
        """
        from_id = f"{_TRACKS}/{nd_id}"
        query = """
        FOR edge IN @@collection
            FILTER edge._from == @from_id
            LIMIT 1
            RETURN edge._to
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"from_id": from_id, "@collection": _HAS_ND_ID},
        )
        result: list[str] = list(cursor)
        cursor.close(ignore_missing=True)
        return result[0] if result else None

    def resolve_file_to_nd(self, file_id: str) -> str | None:
        """Resolve a Nomarr file document ID to a Navidrome track ID.

        Reverse lookup on ``has_nd_id`` using ``_to``.

        Returns:
            Navidrome track ``_key`` or None.
        """
        query = """
        FOR edge IN @@collection
            FILTER edge._to == @file_id
            LIMIT 1
            RETURN PARSE_IDENTIFIER(edge._from).key
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"file_id": file_id, "@collection": _HAS_ND_ID},
        )
        result: list[str] = list(cursor)
        cursor.close(ignore_missing=True)
        return result[0] if result else None

    def bulk_resolve_nd_to_files(self, nd_ids: list[str]) -> dict[str, str]:
        """Resolve multiple Navidrome IDs to Nomarr file IDs.

        Returns:
            Dict mapping nd_id → file document ID.  Only contains entries
            where a ``has_nd_id`` edge exists.
        """
        if not nd_ids:
            return {}

        full_ids = [f"{_TRACKS}/{nd_id}" for nd_id in nd_ids]
        query = """
        FOR edge IN @@collection
            FILTER edge._from IN @full_ids
            RETURN { nd_id: PARSE_IDENTIFIER(edge._from).key, file_id: edge._to }
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"full_ids": full_ids, "@collection": _HAS_ND_ID},
        )
        result: dict[str, str] = {row["nd_id"]: row["file_id"] for row in cursor}
        cursor.close(ignore_missing=True)
        return result

    def bulk_resolve_files_to_nd(self, file_ids: list[str]) -> dict[str, str]:
        """Resolve multiple Nomarr file IDs to Navidrome track IDs.

        Reverse bulk lookup on ``has_nd_id`` using ``_to``.

        Returns:
            Dict mapping file document ID → nd_id.  Only contains entries
            where a ``has_nd_id`` edge exists.
        """
        if not file_ids:
            return {}

        query = """
        FOR edge IN @@collection
            FILTER edge._to IN @file_ids
            RETURN { file_id: edge._to, nd_id: PARSE_IDENTIFIER(edge._from).key }
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={"file_ids": file_ids, "@collection": _HAS_ND_ID},
        )
        result: dict[str, str] = {row["file_id"]: row["nd_id"] for row in cursor}
        cursor.close(ignore_missing=True)
        return result
