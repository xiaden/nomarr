from __future__ import annotations

from typing import Any

from arango.exceptions import DocumentInsertError

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

from ._helpers import Document, _extract_key
from .pipeline_state_ops import PipelineStateOpsMixin
from .worker_claim_ops import WorkerClaimOpsMixin


class AppAqlOperations(WorkerClaimOpsMixin, PipelineStateOpsMixin):
    """Thin Tier 2 bindings for app-domain persistence collections."""

    META_COLLECTION = CollectionNames.META.value
    LOCK_COLLECTION = CollectionNames.LOCKS.value
    WORKER_CLAIM_COLLECTION = CollectionNames.WORKER_CLAIMS.value
    HEALTH_COLLECTION = CollectionNames.HEALTH.value
    VRAM_PROMISE_COLLECTION = CollectionNames.VRAM_PROMISES.value
    PIPELINE_STATE_COLLECTION = CollectionNames.LIBRARY_PIPELINE_STATES.value
    PIPELINE_STATE_EDGE_COLLECTION = CollectionNames.LIBRARY_HAS_PIPELINE_STATE.value
    FILE_STATE_EDGE_COLLECTION = CollectionNames.FILE_HAS_STATE.value
    SCAN_COLLECTION = CollectionNames.LIBRARY_SCANS.value
    LIBRARY_SCAN_EDGE_COLLECTION = CollectionNames.LIBRARY_HAS_SCAN.value
    MIGRATION_COLLECTION = CollectionNames.APPLIED_MIGRATIONS.value
    SESSION_COLLECTION = CollectionNames.SESSIONS.value
    WORKER_RESTART_POLICY_COLLECTION = CollectionNames.WORKER_RESTART_POLICY.value
    CALIBRATION_STATE_COLLECTION = CollectionNames.CALIBRATION_STATE.value

    META_FIELDS = frozenset({"key", "value"})
    MIGRATION_FIELDS = frozenset({"name", "status", "applied_at", "started_at", "migration_version", "duration_ms"})
    LOCK_FIELDS = frozenset({"document_reference", "lock_type", "expires_at", "acquired_at", "holder", "status"})
    WORKER_CLAIM_FIELDS = frozenset({"file_id", "worker_id", "claimed_at", "claim_type", "status"})
    HEALTH_FIELDS = frozenset(
        {
            "component",
            "component_id",
            "component_type",
            "status",
            "message",
            "last_heartbeat",
            "current_job",
            "metadata",
            "pid",
            "exit_code",
            "restart_count",
            "last_restart",
            "error",
            "last_snapshot",
            "created_at",
            "snapshot_type",
        },
    )
    VRAM_PROMISE_FIELDS = frozenset(
        {"worker_id", "pid", "model_path", "promised_mb", "total_mb", "used_mb", "last_seen_ms"}
    )
    PIPELINE_STATE_FIELDS = frozenset({"library_key", "pipeline_state"})
    SCAN_FIELDS = frozenset({"library_key"})
    SESSION_FIELDS = frozenset({"session_id", "user_id", "expiry_timestamp"})
    WORKER_RESTART_POLICY_FIELDS = frozenset(
        {
            "component_id",
            "restart_count",
            "last_restart_wall_ms",
            "failed_at_wall_ms",
            "failure_reason",
            "updated_at_wall_ms",
        }
    )

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def insert_lock(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.LOCK_COLLECTION, payload)

    def upsert_lock(self, resource_id: str, payload: dict[str, Any]) -> None:
        merged_payload = dict(payload)
        merged_payload.setdefault("document_reference", resource_id)
        primitives.upsert_by_field(self._db, self.LOCK_COLLECTION, "document_reference", resource_id, merged_payload)

    def release_lock(self, resource_id: str) -> None:
        primitives.delete_many_by_field(
            self._db,
            self.LOCK_COLLECTION,
            "document_reference",
            resource_id,
            allowed_fields=self.LOCK_FIELDS,
        )

    def get_lock(self, resource_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.LOCK_COLLECTION,
            "document_reference",
            resource_id,
            limit=1,
            allowed_fields=self.LOCK_FIELDS,
        )
        return results[0] if results else None

    def acquire_lock(self, resource_id: str, payload: dict[str, Any]) -> bool:
        merged_payload = dict(payload)
        merged_payload.setdefault("document_reference", resource_id)
        try:
            primitives.insert_document(self._db, self.LOCK_COLLECTION, merged_payload)
        except DocumentInsertError:
            return False
        return True

    def list_locks(self) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.LOCK_COLLECTION,
            filters={},
            sort_field="document_reference",
            limit=None,
            allowed_fields=self.LOCK_FIELDS,
        )

    def get_health(self, component_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.HEALTH_COLLECTION,
            "component_id",
            component_id,
            limit=1,
            allowed_fields=self.HEALTH_FIELDS,
        )
        return results[0] if results else None

    def count_healthy(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.status == @status
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.HEALTH_COLLECTION, "status": "healthy"},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def list_worker_health(self) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.HEALTH_COLLECTION,
            filters={"component_type": "worker"},
            sort_field="component_id",
            limit=None,
            allowed_fields=self.HEALTH_FIELDS,
        )

    def get_meta(self, key: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.META_COLLECTION,
            "key",
            key,
            limit=1,
            allowed_fields=self.META_FIELDS,
        )
        return results[0] if results else None

    def get_schema_version(self) -> str | None:
        """Get the schema version stored as ``_key='version'`` in meta."""
        cursor = self._db.aql.execute(
            "FOR doc IN @@collection FILTER doc._key == 'version' LIMIT 1 RETURN doc.value",
            bind_vars={"@collection": self.META_COLLECTION},
        )
        results = list(cursor)
        return str(results[0]) if results else None

    def upsert_meta(self, key: str, payload: dict[str, Any]) -> None:
        merged_payload = dict(payload)
        merged_payload.setdefault("key", key)
        primitives.upsert_by_field(self._db, self.META_COLLECTION, "key", key, merged_payload)

    def delete_meta(self, key: str) -> None:
        primitives.delete_many_by_field(
            self._db,
            self.META_COLLECTION,
            "key",
            key,
            allowed_fields=self.META_FIELDS,
        )

    def list_meta_keys_by_prefix(self, prefix: str) -> list[str]:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER LIKE(doc.key, CONCAT(@prefix, "%"), false)
                SORT doc.key
                RETURN doc.key
            """,
            bind_vars={"@collection": self.META_COLLECTION, "prefix": prefix},
        )
        return [key for key in cursor if isinstance(key, str)]

    def upsert_migration(self, name: str, fields: dict[str, Any]) -> None:
        merged_fields = dict(fields)
        merged_fields.setdefault("name", name)
        primitives.upsert_by_field(self._db, self.MIGRATION_COLLECTION, "name", name, merged_fields)

    def list_migrations(self) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.MIGRATION_COLLECTION,
            filters={},
            sort_field="name",
            limit=None,
            allowed_fields=self.MIGRATION_FIELDS,
        )

    def upsert_vram_promise(self, payload: dict[str, Any]) -> None:
        promise_key = payload.get("_key")
        worker_id = payload.get("worker_id")
        if isinstance(promise_key, str) and promise_key:
            self._db.aql.execute(
                """
                UPSERT { _key: @promise_key }
                    INSERT MERGE(@payload, { _key: @promise_key })
                    UPDATE @payload
                    IN @@collection
                """,
                bind_vars={
                    "@collection": self.VRAM_PROMISE_COLLECTION,
                    "promise_key": promise_key,
                    "payload": payload,
                },
            )
            return
        if isinstance(worker_id, str) and worker_id:
            primitives.upsert_by_field(self._db, self.VRAM_PROMISE_COLLECTION, "worker_id", worker_id, payload)
            return
        primitives.insert_document(self._db, self.VRAM_PROMISE_COLLECTION, payload)

    def get_vram_promises(self) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.VRAM_PROMISE_COLLECTION,
            filters={},
            sort_field="last_seen_ms",
            limit=None,
            allowed_fields=self.VRAM_PROMISE_FIELDS,
        )

    def delete_vram_promise(self, promise_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.VRAM_PROMISE_COLLECTION, [_extract_key(promise_id)])

    def count_vram_promises(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.VRAM_PROMISE_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def truncate_health(self) -> None:
        self._truncate_collection(self.HEALTH_COLLECTION)

    def upsert_health(self, component_id: str, fields: dict[str, Any]) -> None:
        merged = dict(fields)
        merged.setdefault("component_id", component_id)
        primitives.upsert_by_field(self._db, self.HEALTH_COLLECTION, "component_id", component_id, merged)

    def update_health(self, component_id: str, fields: dict[str, Any]) -> None:
        existing = self.get_health(component_id)
        if existing is None:
            return
        key = existing.get("_key")
        if isinstance(key, str):
            primitives.update_document_by_key(self._db, self.HEALTH_COLLECTION, key, fields)

    def insert_session(self, payload: list[dict[str, Any]]) -> None:
        for doc in payload:
            primitives.insert_document(self._db, self.SESSION_COLLECTION, doc)

    def delete_session(self, session_id: str) -> None:
        primitives.delete_many_by_field(
            self._db,
            self.SESSION_COLLECTION,
            "session_id",
            session_id,
            allowed_fields=self.SESSION_FIELDS,
        )

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[Document]:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.expiry_timestamp <= @ts
                LIMIT @limit
                RETURN doc
            """,
            bind_vars={"@collection": self.SESSION_COLLECTION, "ts": timestamp_ms, "limit": limit},
        )
        return list(cursor)

    def count_sessions(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.SESSION_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def delete_sessions_by_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc._id IN @ids
                REMOVE doc IN @@collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"@collection": self.SESSION_COLLECTION, "ids": ids},
        )

    def get_active_sessions(self, not_before_ms: int, limit: int) -> list[Document]:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc.expiry_timestamp >= @ts
                LIMIT @limit
                RETURN doc
            """,
            bind_vars={"@collection": self.SESSION_COLLECTION, "ts": not_before_ms, "limit": limit},
        )
        return list(cursor)

    def get_worker_restart_policy(self, component_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.WORKER_RESTART_POLICY_COLLECTION,
            "component_id",
            component_id,
            limit=1,
            allowed_fields=self.WORKER_RESTART_POLICY_FIELDS,
        )
        return results[0] if results else None

    def update_worker_restart_policy(self, component_id: str, fields: dict[str, Any]) -> None:
        existing = self.get_worker_restart_policy(component_id)
        if existing is None:
            return
        key = existing.get("_key")
        if isinstance(key, str):
            primitives.update_document_by_key(self._db, self.WORKER_RESTART_POLICY_COLLECTION, key, fields)

    def upsert_worker_restart_policy(self, component_id: str, fields: dict[str, Any]) -> None:
        merged = dict(fields)
        merged.setdefault("component_id", component_id)
        primitives.upsert_by_field(
            self._db, self.WORKER_RESTART_POLICY_COLLECTION, "component_id", component_id, merged
        )

    def count_calibration_states(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.CALIBRATION_STATE_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"@collection": collection_name},
        )
