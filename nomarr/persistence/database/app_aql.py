from __future__ import annotations

from typing import Any

from arango.exceptions import DocumentInsertError

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class AppAqlOperations:
    """Thin Tier 2 bindings for app-domain persistence collections."""

    META_COLLECTION = "meta"
    LOCK_COLLECTION = "locks"
    WORKER_CLAIM_COLLECTION = "worker_claims"
    HEALTH_COLLECTION = "health"
    VRAM_PROMISE_COLLECTION = "vram_promises"
    PIPELINE_STATE_COLLECTION = "library_pipeline_states"
    PIPELINE_STATE_EDGE_COLLECTION = "library_has_pipeline_state"
    FILE_STATE_EDGE_COLLECTION = "file_has_state"
    SCAN_COLLECTION = "library_scans"
    LIBRARY_SCAN_EDGE_COLLECTION = "library_has_scan"
    MIGRATION_COLLECTION = "applied_migrations"
    SESSION_COLLECTION = "sessions"
    WORKER_RESTART_POLICY_COLLECTION = "worker_restart_policy"
    CALIBRATION_STATE_COLLECTION = "calibration_state"

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
        lock_docs = primitives.get_many_by_field(
            self._db,
            self.LOCK_COLLECTION,
            "document_reference",
            resource_id,
            limit=None,
            allowed_fields=self.LOCK_FIELDS,
        )
        keys = [doc["_key"] for doc in lock_docs if isinstance(doc.get("_key"), str)]
        primitives.delete_many_by_keys(self._db, self.LOCK_COLLECTION, keys)

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

    def insert_worker_claim(self, payload: dict[str, Any]) -> None:
        primitives.insert_document(self._db, self.WORKER_CLAIM_COLLECTION, payload)

    def claim_file(self, file_id: str, worker_id: str, payload: dict[str, Any]) -> None:
        merged_payload = dict(payload)
        merged_payload.setdefault("file_id", _as_document_id("library_files", file_id))
        merged_payload.setdefault("worker_id", worker_id)
        primitives.insert_document(self._db, self.WORKER_CLAIM_COLLECTION, merged_payload)

    def release_claim(self, file_id: str) -> None:
        claim_docs = primitives.get_many_by_field(
            self._db,
            self.WORKER_CLAIM_COLLECTION,
            "file_id",
            _as_document_id("library_files", file_id),
            limit=None,
            allowed_fields=self.WORKER_CLAIM_FIELDS,
        )
        keys = [doc["_key"] for doc in claim_docs if isinstance(doc.get("_key"), str)]
        primitives.delete_many_by_keys(self._db, self.WORKER_CLAIM_COLLECTION, keys)

    def delete_claims_for_workers(self, worker_ids: list[str]) -> int:
        if not worker_ids:
            return 0
        rows = primitives.execute(
            self._db,
            """
            FOR claim IN @@collection
                FILTER claim.worker_id IN @worker_ids
                REMOVE claim IN @@collection
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
                REMOVE claim IN @@collection
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
                REMOVE claim IN @@collection
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
                REMOVE claim IN @@collection
            """,
            bind_vars={"@collection": self.WORKER_CLAIM_COLLECTION},
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

    def upsert_meta(self, key: str, payload: dict[str, Any]) -> None:
        merged_payload = dict(payload)
        merged_payload.setdefault("key", key)
        primitives.upsert_by_field(self._db, self.META_COLLECTION, "key", key, merged_payload)

    def delete_meta(self, key: str) -> None:
        meta_docs = primitives.get_many_by_field(
            self._db,
            self.META_COLLECTION,
            "key",
            key,
            limit=None,
            allowed_fields=self.META_FIELDS,
        )
        keys = [doc["_key"] for doc in meta_docs if isinstance(doc.get("_key"), str)]
        primitives.delete_many_by_keys(self._db, self.META_COLLECTION, keys)

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

    def upsert_pipeline_state(self, library_id: str, state: str) -> None:
        library_key = _extract_key(library_id)
        payload = {"library_key": library_key, "pipeline_state": state}
        primitives.upsert_by_field(self._db, self.PIPELINE_STATE_COLLECTION, "library_key", library_key, payload)

    def get_pipeline_state_doc(self, library_id: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            "library_key",
            _extract_key(library_id),
            limit=1,
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )
        return results[0] if results else None

    def update_pipeline_state(self, library_id: str, state: str) -> None:
        pipeline_state_doc = self.get_pipeline_state_doc(library_id)
        if pipeline_state_doc is None:
            return
        pipeline_key = pipeline_state_doc.get("_key")
        if isinstance(pipeline_key, str):
            primitives.update_document_by_key(
                self._db,
                self.PIPELINE_STATE_COLLECTION,
                pipeline_key,
                {"pipeline_state": state},
            )

    def delete_pipeline_state(self, library_id: str) -> int:
        pipeline_state_docs = primitives.get_many_by_field(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            "library_key",
            _extract_key(library_id),
            limit=None,
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )
        keys = [doc["_key"] for doc in pipeline_state_docs if isinstance(doc.get("_key"), str)]
        if not keys:
            return 0
        return primitives.delete_many_by_keys(self._db, self.PIPELINE_STATE_COLLECTION, keys)

    def count_pipeline_states(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.PIPELINE_STATE_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def list_libraries_in_pipeline_state(self, state: str) -> list[Document]:
        return primitives.get_filtered_docs(
            self._db,
            self.PIPELINE_STATE_COLLECTION,
            filters={"pipeline_state": state},
            sort_field="library_key",
            limit=None,
            allowed_fields=self.PIPELINE_STATE_FIELDS,
        )

    def delete_pipeline_state_edges_for_library(self, library_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.PIPELINE_STATE_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
            },
        )

    def list_file_docs_in_state(self, state: str, *, limit: int | None = None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.FILE_STATE_EDGE_COLLECTION,
            "state_id": _as_document_id("file_states", state),
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._to == @state_id",
            "    LET file = DOCUMENT(edge._from)",
            "    FILTER file != null",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def get_state_edges_for_files(self, file_ids: list[str]) -> list[Document]:
        normalized_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_ids:
            return []
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from IN @file_ids
                SORT edge._from, edge._to, edge._key
                RETURN edge
            """,
            {"@collection": self.FILE_STATE_EDGE_COLLECTION, "file_ids": normalized_ids},
        )

    def delete_scan_records_for_library(self, library_key: str) -> int:
        scan_docs = primitives.get_many_by_field(
            self._db,
            self.SCAN_COLLECTION,
            "library_key",
            library_key,
            limit=None,
            allowed_fields=self.SCAN_FIELDS,
        )
        keys = [doc["_key"] for doc in scan_docs if isinstance(doc.get("_key"), str)]
        if not keys:
            return 0
        return primitives.delete_many_by_keys(self._db, self.SCAN_COLLECTION, keys)

    def upsert_library_scan_edge(self, library_id: str, scan_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @library_id, _to: @scan_id }
                INSERT { _from: @library_id, _to: @scan_id }
                UPDATE {}
                IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_SCAN_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
                "scan_id": _as_document_id(self.SCAN_COLLECTION, scan_id),
            },
        )

    def delete_library_scan_edge(self, library_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_SCAN_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
            },
        )

    def truncate_file_state_edges(self) -> None:
        self._truncate_collection(self.FILE_STATE_EDGE_COLLECTION)

    def truncate_scan_records(self) -> None:
        self._truncate_collection(self.SCAN_COLLECTION)

    def truncate_library_scan_edges(self) -> None:
        self._truncate_collection(self.LIBRARY_SCAN_EDGE_COLLECTION)

    def truncate_pipeline_states(self) -> None:
        self._truncate_collection(self.PIPELINE_STATE_COLLECTION)

    def truncate_pipeline_state_edges(self) -> None:
        self._truncate_collection(self.PIPELINE_STATE_EDGE_COLLECTION)

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
        docs = primitives.get_many_by_field(
            self._db, self.SESSION_COLLECTION, "session_id", session_id, limit=None, allowed_fields=self.SESSION_FIELDS
        )
        keys = [doc["_key"] for doc in docs if isinstance(doc.get("_key"), str)]
        if keys:
            primitives.delete_many_by_keys(self._db, self.SESSION_COLLECTION, keys)

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
                REMOVE doc IN @@collection
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
                REMOVE doc IN @@collection
            """,
            bind_vars={"@collection": collection_name},
        )
