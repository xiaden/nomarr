"""Navidrome song map operations for ArangoDB.

Persisted bidirectional mapping between Navidrome mediafile IDs and Nomarr
library_files document IDs. Supports efficient lookups in both directions
for vector similarity API and playlist push features.

Collection schema (navidrome_song_map):
    _key:      Navidrome mediafile ID (primary key)
    file_id:   Nomarr document ID (e.g. 'library_files/abc123')
    nd_path:   Original file path as reported by Navidrome
    synced_at: Timestamp in milliseconds when mapping was created/updated
"""

from typing import TYPE_CHECKING, Any

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

_COLLECTION = "navidrome_song_map"


class NavidromeSongMapOperations:
    """CRUD operations for the navidrome_song_map collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection(_COLLECTION)

    def upsert_batch(self, mappings: list[dict[str, Any]]) -> int:
        """Upsert a batch of Navidrome-to-Nomarr ID mappings.

        Each mapping dict must contain ``nd_id``, ``file_id``, and ``nd_path``.
        Uses AQL UPSERT to insert new mappings or update existing ones.

        Args:
            mappings: List of dicts with keys ``nd_id``, ``file_id``, ``nd_path``.

        Returns:
            Number of documents upserted.
        """
        if not mappings:
            return 0

        ts = now_ms().value
        docs = [
            {
                "_key": m["nd_id"],
                "file_id": m["file_id"],
                "nd_path": m["nd_path"],
                "synced_at": ts,
            }
            for m in mappings
        ]

        query = """
        FOR doc IN @docs
            UPSERT { _key: doc._key }
            INSERT doc
            UPDATE { file_id: doc.file_id, nd_path: doc.nd_path, synced_at: doc.synced_at }
            IN @@collection
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
            query,
            bind_vars={"docs": docs, "@collection": _COLLECTION},
        )
        cursor.close()
        return len(docs)

    def lookup_by_nd_id(self, nd_id: str) -> str | None:
        """Look up a Nomarr file_id by Navidrome mediafile ID.

        Args:
            nd_id: Navidrome mediafile ID.

        Returns:
            Nomarr file_id or None if not mapped.
        """
        query = """
        FOR doc IN @@collection
            FILTER doc._key == @nd_id
            RETURN doc.file_id
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
            query,
            bind_vars={"nd_id": nd_id, "@collection": _COLLECTION},
        )
        result: list[str] = list(cursor)
        cursor.close()
        return result[0] if result else None

    def lookup_by_file_id(self, file_id: str) -> str | None:
        """Look up a Navidrome mediafile ID by Nomarr file_id.

        Uses the unique persistent index on file_id for fast lookups.

        Args:
            file_id: Nomarr document ID (e.g. 'library_files/abc123').

        Returns:
            Navidrome mediafile ID (_key) or None if not mapped.
        """
        query = """
        FOR doc IN @@collection
            FILTER doc.file_id == @file_id
            RETURN doc._key
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
            query,
            bind_vars={"file_id": file_id, "@collection": _COLLECTION},
        )
        result: list[str] = list(cursor)
        cursor.close()
        return result[0] if result else None

    def bulk_lookup_by_file_ids(self, file_ids: list[str]) -> dict[str, str]:
        """Look up Navidrome IDs for multiple Nomarr file_ids.

        Args:
            file_ids: List of Nomarr document IDs.

        Returns:
            Dict mapping file_id -> Navidrome mediafile ID (_key).
            Only contains entries for file_ids that have mappings.
        """
        if not file_ids:
            return {}

        query = """
        FOR doc IN @@collection
            FILTER doc.file_id IN @file_ids
            RETURN { file_id: doc.file_id, nd_id: doc._key }
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
            query,
            bind_vars={"file_ids": file_ids, "@collection": _COLLECTION},
        )
        result: dict[str, str] = {row["file_id"]: row["nd_id"] for row in cursor}
        cursor.close()
        return result

    def count(self) -> int:
        """Return the total number of mappings in the collection."""
        query = "RETURN LENGTH(@@collection)"
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
            query,
            bind_vars={"@collection": _COLLECTION},
        )
        result: list[int] = list(cursor)
        cursor.close()
        return result[0] if result else 0

    def truncate(self) -> None:
        """Remove all documents from the collection."""
        self.collection.truncate()  # type: ignore[union-attr, assignment]  # python-arango stubs return union for sync/async/batch; we only use sync
