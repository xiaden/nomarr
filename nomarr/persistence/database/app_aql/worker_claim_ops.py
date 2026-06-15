from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.persistence.aql import primitives

from ._helpers import Document, _as_document_id

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class WorkerClaimOpsMixin:
    """Mixin for worker claim CRUD and query operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    ``self.WORKER_CLAIM_COLLECTION``, and ``self.WORKER_CLAIM_FIELDS``.
    """

    _db: SafeDatabase
    WORKER_CLAIM_COLLECTION: str
    WORKER_CLAIM_FIELDS: frozenset[str]

    def insert_worker_claim(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.WORKER_CLAIM_COLLECTION, payload)

    def claim_file(self, file_id: str, worker_id: str, payload: dict[str, Any]) -> None:
        merged_payload = dict(payload)
        merged_payload.setdefault("file_id", _as_document_id("library_files", file_id))
        merged_payload.setdefault("worker_id", worker_id)
        primitives.insert_document(self._db, self.WORKER_CLAIM_COLLECTION, merged_payload)

    def release_claim(self, file_id: str) -> None:
        primitives.delete_many_by_field(
            self._db,
            self.WORKER_CLAIM_COLLECTION,
            "file_id",
            _as_document_id("library_files", file_id),
            allowed_fields=self.WORKER_CLAIM_FIELDS,
        )

    def delete_claims_for_workers(self, worker_ids: list[str]) -> int:
        if not worker_ids:
            return 0
        rows = primitives.execute(
            self._db,
            """
            FOR claim IN @@collection
                FILTER claim.worker_id IN @worker_ids
                REMOVE claim IN @@collection OPTIONS { ignoreErrors: true }
                RETURN 1
            """,
            {"@collection": self.WORKER_CLAIM_COLLECTION, "worker_ids": worker_ids},
        )
        return len(rows)

    def delete_claims_for_files(self, file_ids: list[str]) -> int:
        normalized_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_ids:
            return 0
        rows = primitives.execute(
            self._db,
            """
            FOR claim IN @@collection
                FILTER claim.file_id IN @file_ids
                REMOVE claim IN @@collection OPTIONS { ignoreErrors: true }
                RETURN 1
            """,
            {"@collection": self.WORKER_CLAIM_COLLECTION, "file_ids": normalized_ids},
        )
        return len(rows)

    def steal_claim(self, payload: dict[str, Any], now: int, lease_ms: int) -> bool:
        file_id = payload.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            msg = "Claim payload must include a non-empty file_id"
            raise ValueError(msg)
        normalized_file_id = _as_document_id("library_files", file_id)
        merged_payload = dict(payload)
        merged_payload["file_id"] = normalized_file_id
        rows = primitives.execute(
            self._db,
            """
            LET matching_claims = (
                FOR claim IN @@collection
                    FILTER claim.file_id == @file_id
                    SORT claim.claimed_at DESC, claim._key DESC
                    RETURN claim
            )
            LET active_claim = FIRST(
                FOR claim IN matching_claims
                    FILTER TO_NUMBER(claim.claimed_at) >= @stale_before
                    LIMIT 1
                    RETURN 1
            )
            FILTER active_claim == null
            FOR claim IN matching_claims
                REMOVE claim IN @@collection OPTIONS { ignoreErrors: true }
            INSERT @payload INTO @@collection
            RETURN NEW._id
            """,
            {
                "@collection": self.WORKER_CLAIM_COLLECTION,
                "file_id": normalized_file_id,
                "stale_before": now - lease_ms,
                "payload": merged_payload,
            },
        )
        return bool(rows)

    def list_claims(self) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR claim IN @@collection
                SORT claim._key
                RETURN claim
            """,
            {"@collection": self.WORKER_CLAIM_COLLECTION},
        )

    def aggregate_worker_claims(self) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR claim IN @@collection
                COLLECT status = claim.status WITH COUNT INTO count
                SORT status
                RETURN { status: status, count: count }
            """,
            {"@collection": self.WORKER_CLAIM_COLLECTION},
        )

    def count_worker_claims(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR claim IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.WORKER_CLAIM_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def count_claims(self) -> int:
        return self.count_worker_claims()

    def delete_all_worker_claims(self) -> None:
        self._db.aql.execute(
            """
            FOR claim IN @@collection
                REMOVE claim IN @@collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"@collection": self.WORKER_CLAIM_COLLECTION},
        )
