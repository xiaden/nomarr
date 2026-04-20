"""Integration tests for the vector hot/cold lifecycle."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.components.platform.arango_bootstrap_comp import (
    _create_vectors_track_collections,
)
from nomarr.persistence.db import Database
from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
from nomarr.services.domain.vector_search_svc import VectorSearchService


def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
    """Match the deterministic key strategy from vectors_track operations."""
    return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()


class VectorLifecycleHarness:
    """In-memory representation of hot and cold vector collections."""

    def __init__(self) -> None:
        self.hot_docs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.cold_docs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.known_backbones: set[str] = set()
        self.cold_collections: set[str] = set()
        self.vector_indexes: set[str] = set()
        self.promote_log: list[tuple[str, int]] = []
        self._ts = 0

    def _next_timestamp(self) -> int:
        self._ts += 1
        return self._ts

    def register_backbone(self, backbone_id: str) -> None:
        self.known_backbones.add(backbone_id)

    def ensure_cold_collection(self, backbone_id: str) -> None:
        self.cold_collections.add(backbone_id)

    def install_vector_index(self, backbone_id: str) -> None:
        self.ensure_cold_collection(backbone_id)
        self.vector_indexes.add(backbone_id)

    def has_vector_index(self, backbone_id: str) -> bool:
        return backbone_id in self.vector_indexes

    def upsert_hot(
        self,
        backbone_id: str,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        self.register_backbone(backbone_id)
        key = _make_vector_key(file_id, model_suite_hash)
        self.hot_docs[backbone_id][key] = {
            "_key": key,
            "file_id": file_id,
            "model_suite_hash": model_suite_hash,
            "embed_dim": embed_dim,
            "vector": vector,
            "num_segments": num_segments,
            "created_at": self._next_timestamp(),
        }

    def seed_cold(self, backbone_id: str, doc: dict[str, Any]) -> None:
        self.ensure_cold_collection(backbone_id)
        key = doc.get("_key") or _make_vector_key(doc["file_id"], doc.get("model_suite_hash", "default"))
        stored = doc | {"_key": key, "created_at": self._next_timestamp()}
        self.cold_docs[backbone_id][key] = stored

    def move_hot_to_cold(self, backbone_id: str, nlists: int) -> None:
        self.ensure_cold_collection(backbone_id)
        self.install_vector_index(backbone_id)
        hot_entries = self.hot_docs[backbone_id]
        cold_entries = self.cold_docs[backbone_id]
        cold_entries.update(hot_entries)
        hot_entries.clear()
        self.promote_log.append((backbone_id, nlists))

    def hot_count(self, backbone_id: str) -> int:
        return len(self.hot_docs[backbone_id])

    def cold_count(self, backbone_id: str) -> int:
        return len(self.cold_docs[backbone_id])

    def get_hot_vector(self, backbone_id: str, file_id: str) -> dict[str, Any] | None:
        candidates = [doc for doc in self.hot_docs[backbone_id].values() if doc["file_id"] == file_id]
        if not candidates:
            return None
        return max(candidates, key=lambda doc: doc["created_at"])

    def get_cold_vector(self, backbone_id: str, file_id: str) -> dict[str, Any] | None:
        candidates = [doc for doc in self.cold_docs[backbone_id].values() if doc["file_id"] == file_id]
        if not candidates:
            return None
        return max(candidates, key=lambda doc: doc["created_at"])

    def search_cold(self, backbone_id: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
        docs = list(self.cold_docs[backbone_id].values())
        if not docs:
            return []

        def score(doc: dict[str, Any]) -> float:
            stored = cast("list[float]", doc["vector"])
            return float(sum(a * b for a, b in zip(vector, stored, strict=True)))

        sorted_docs = sorted(docs, key=score, reverse=True)[:limit]
        return [doc | {"score": score(doc)} for doc in sorted_docs]

    def delete_hot(self, backbone_id: str, file_id: str) -> int:
        hot_entries = self.hot_docs[backbone_id]
        keys_to_delete = [key for key, doc in hot_entries.items() if doc["file_id"] == file_id]
        for key in keys_to_delete:
            del hot_entries[key]
        return len(keys_to_delete)

    def delete_cold(self, backbone_id: str, file_id: str) -> int:
        cold_entries = self.cold_docs[backbone_id]
        keys_to_delete = [key for key, doc in cold_entries.items() if doc["file_id"] == file_id]
        for key in keys_to_delete:
            del cold_entries[key]
        return len(keys_to_delete)


class FakeArangoCollection:
    """Minimal stub that exposes index metadata for has_vector_index()."""

    def __init__(self, harness: VectorLifecycleHarness, name: str) -> None:
        self.harness = harness
        self.name = name

    @staticmethod
    def _extract_backbone(name: str) -> str:
        """Extract backbone id from a per-library collection name.

        Collection names follow the pattern
        ``vectors_track_{tier}__{backbone}__{library_key}``.
        We split on ``"__"`` and take the second segment.
        """
        parts = name.split("__")
        return parts[1] if len(parts) >= 2 else name

    def indexes(self) -> list[dict[str, Any]]:
        if "vectors_track_cold__" in self.name:
            backbone = self._extract_backbone(self.name)
            if self.harness.has_vector_index(backbone):
                return [{"type": "vector"}]
        return []

    def truncate(self) -> None:
        backbone = self._extract_backbone(self.name)
        if "vectors_track_hot__" in self.name:
            self.harness.hot_docs[backbone].clear()
        else:
            self.harness.cold_docs[backbone].clear()


class FakeArangoHandle:
    """Surface has_collection/collection methods expected by services."""

    def __init__(self, harness: VectorLifecycleHarness) -> None:
        self.harness = harness
        self._collections: set[str] = set()
        self.aql = self

    def register_collection(self, name: str) -> None:
        self._collections.add(name)

    def has_collection(self, name: str) -> bool:
        if name in self._collections:
            return True
        # Also check harness state for backwards-compat with older test patterns
        backbone = FakeArangoCollection._extract_backbone(name)
        if "vectors_track_hot__" in name:
            return backbone in self.harness.known_backbones
        if "vectors_track_cold__" in name:
            return backbone in self.harness.cold_collections
        return False

    def collection(self, name: str) -> FakeArangoCollection:
        return FakeArangoCollection(self.harness, name)

    def execute(self, query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        """Handle the minimal AQL surface exercised by the vector tests."""
        del query
        file_id = None if bind_vars is None else bind_vars.get("file_id")
        if isinstance(file_id, str) and file_id.startswith("library_files/"):
            return iter(["libraries/test_lib"])
        return iter([])


class FakeHotOperations:
    """Subset of hot operations used by the services/tests."""

    def __init__(self, harness: VectorLifecycleHarness, backbone_id: str) -> None:
        self.harness = harness
        self.backbone_id = backbone_id

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        self.harness.upsert_hot(
            backbone_id=self.backbone_id,
            file_id=file_id,
            model_suite_hash=model_suite_hash,
            embed_dim=embed_dim,
            vector=vector,
            num_segments=num_segments,
        )

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        return self.harness.get_hot_vector(self.backbone_id, file_id)

    def count(self) -> int:
        return self.harness.hot_count(self.backbone_id)

    def delete_by_file_id(self, file_id: str) -> int:
        return self.harness.delete_hot(self.backbone_id, file_id)

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        return sum(self.delete_by_file_id(file_id) for file_id in file_ids)


class FakeColdOperations:
    """Subset of cold operations used by the services/tests."""

    def __init__(self, harness: VectorLifecycleHarness, backbone_id: str) -> None:
        self.harness = harness
        self.backbone_id = backbone_id

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        return self.harness.get_cold_vector(self.backbone_id, file_id)

    def ann_search(self, vector: list[float], limit: int, *, nprobe: int = 10) -> list[dict[str, Any]]:
        del nprobe
        return self.harness.search_cold(self.backbone_id, vector, limit)

    def count(self) -> int:
        return self.harness.cold_count(self.backbone_id)

    def delete_by_file_id(self, file_id: str) -> int:
        return self.harness.delete_cold(self.backbone_id, file_id)

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        return sum(self.delete_by_file_id(file_id) for file_id in file_ids)


class FakeVectorsTrackMaintenance:
    """Minimal maintenance namespace used by constructor-backed vector helpers."""

    def __init__(self, harness: VectorLifecycleHarness, backbone_id: str) -> None:
        self.harness = harness
        self.backbone_id = backbone_id

    def ensure_cold_collection(self) -> None:
        self.harness.ensure_cold_collection(self.backbone_id)

    def get_stats(self) -> dict[str, int | bool]:
        return {
            "hot_count": self.harness.hot_count(self.backbone_id),
            "cold_count": self.harness.cold_count(self.backbone_id),
            "index_exists": self.harness.has_vector_index(self.backbone_id),
        }

    def drop_index(self) -> None:
        self.harness.vector_indexes.discard(self.backbone_id)

    def build_index(self, *, embed_dim: int, nlists: int) -> None:
        del embed_dim, nlists
        self.harness.install_vector_index(self.backbone_id)

    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None:
        self.drop_index()
        self.build_index(embed_dim=embed_dim, nlists=nlists)


class FakeDatabaseAdapter:
    """Provides the minimal Database interface needed by the services."""

    def __init__(self, harness: VectorLifecycleHarness) -> None:
        self.harness = harness
        self.db = FakeArangoHandle(harness)
        self.vectors_track: dict[str, FakeHotOperations] = {}
        self._vectors_track_cold: dict[str, FakeColdOperations] = {}
        self._vectors_track_maintenance: dict[str, FakeVectorsTrackMaintenance] = {}
        self.library_files = MagicMock()
        # Default: all file_ids belong to "test_lib"
        self.library_files.get_file_library_key.return_value = "test_lib"
        self.library_contains_file = MagicMock()
        self.library_contains_file._to.get.many.side_effect = self._get_library_contains_file_edges

    def _get_library_contains_file_edges(
        self,
        file_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, str]]:
        del limit, offset
        library_key = self.library_files.get_file_library_key(file_id)
        if not library_key:
            return []
        return [{"_from": f"libraries/{library_key}", "_to": file_id}]

    def register_vectors_track_backbone(self, backbone_id: str, library_key: str = "test_lib") -> FakeHotOperations:
        self.harness.register_backbone(backbone_id)
        self.db.register_collection(f"vectors_track_hot__{backbone_id}__{library_key}")
        return self.vectors_track.setdefault(backbone_id, FakeHotOperations(self.harness, backbone_id))

    def get_vectors_track_cold(self, backbone_id: str, library_key: str = "test_lib") -> FakeColdOperations:
        self.harness.ensure_cold_collection(backbone_id)
        self.db.register_collection(f"vectors_track_cold__{backbone_id}__{library_key}")
        return self._vectors_track_cold.setdefault(backbone_id, FakeColdOperations(self.harness, backbone_id))

    def get_vectors_track_maintenance(
        self,
        backbone_id: str,
        library_key: str = "test_lib",
    ) -> FakeVectorsTrackMaintenance:
        self.db.register_collection(f"vectors_track_hot__{backbone_id}__{library_key}")
        return self._vectors_track_maintenance.setdefault(
            backbone_id,
            FakeVectorsTrackMaintenance(self.harness, backbone_id),
        )


@pytest.fixture
def vector_harness() -> VectorLifecycleHarness:
    return VectorLifecycleHarness()


@pytest.fixture
def fake_database(vector_harness: VectorLifecycleHarness) -> FakeDatabaseAdapter:
    return FakeDatabaseAdapter(vector_harness)


def test_bootstrap_creates_hot_collections_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bootstrap should only create hot collections with indexes."""

    db_mock = MagicMock()

    def _has_collection(name: str) -> bool:
        # The "libraries" collection exists; new per-library vector collections do not
        return name == "libraries"

    db_mock.has_collection.side_effect = _has_collection
    created_collections: list[str] = []
    db_mock.create_collection.side_effect = created_collections.append

    indexed_collections: list[str] = []

    def record_index(
        db_handle: Any,
        collection: str,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        indexed_collections.append(collection)

    monkeypatch.setattr(
        "nomarr.components.platform.arango_bootstrap_comp.discover_backbones",
        lambda _models_dir: ["effnet", "yamnet"],
    )
    monkeypatch.setattr(
        "nomarr.components.platform.arango_bootstrap_comp._ensure_index",
        record_index,
    )
    monkeypatch.setattr(
        "nomarr.components.platform.arango_bootstrap_comp.list_all_library_keys",
        lambda _db: ["lib1"],
    )

    _create_vectors_track_collections(db_mock, models_dir="/tmp/models")

    assert created_collections == [
        "vectors_track_hot__effnet__lib1",
        "vectors_track_hot__yamnet__lib1",
    ]
    assert all(name.startswith("vectors_track_hot__") for name in indexed_collections)
    assert all("cold" not in name for name in created_collections)


def test_upsert_vector_resides_in_hot_until_promotion(
    fake_database: FakeDatabaseAdapter,
) -> None:
    """Vectors stay in hot storage until maintenance promotes them."""

    hot_ops = fake_database.register_vectors_track_backbone("effnet")
    cold_ops = fake_database.get_vectors_track_cold("effnet")

    hot_ops.upsert_vector(
        file_id="library_files/1",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.1, 0.2, 0.3],
        num_segments=4,
    )

    assert fake_database.harness.hot_count("effnet") == 1
    assert cold_ops.get_vector("library_files/1") is None


def test_promote_and_rebuild_moves_hot_vectors_to_cold(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintenance workflow drains hot vectors, builds index, and leaves cold ready."""

    service = VectorMaintenanceService(cast("Database", fake_database), models_dir="/ml-models", config_svc=MagicMock())
    hot_ops = fake_database.register_vectors_track_backbone("effnet")
    hot_ops.upsert_vector(
        file_id="library_files/42",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.4, 0.5, 0.6],
        num_segments=2,
    )

    def fake_workflow(**kwargs: Any) -> None:
        vector_harness.move_hot_to_cold(
            backbone_id=kwargs["backbone_id"],
            nlists=kwargs["nlists"],
        )

    monkeypatch.setattr(
        "nomarr.services.domain.vector_maintenance_svc.promote_and_rebuild_workflow",
        fake_workflow,
    )

    service.promote_and_rebuild("effnet", library_key="test_lib", nlists=48)

    assert vector_harness.hot_count("effnet") == 0
    assert vector_harness.cold_count("effnet") == 1
    assert vector_harness.has_vector_index("effnet")


def test_search_similar_uses_cold_only(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
) -> None:
    """Similarity search must ignore hot data and honor cold-only semantics."""

    service = VectorSearchService(cast("Database", fake_database), config_svc=MagicMock())
    backbone = "effnet"
    hot_ops = fake_database.register_vectors_track_backbone(backbone)
    fake_database.get_vectors_track_cold(backbone)  # ensure cold fixture exists

    hot_ops.upsert_vector(
        file_id="library_files/hot_only",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.9, 0.1, 0.0],
        num_segments=2,
    )

    query_vector = [0.1, 0.9, 0.2]
    vector_harness.seed_cold(
        backbone,
        {
            "file_id": "library_files/cold_doc",
            "model_suite_hash": "suite",
            "vector": query_vector,
            "vector_n": query_vector,
            "embed_dim": 3,
            "num_segments": 2,
        },
    )
    vector_harness.install_vector_index(backbone)

    results = service.search_similar_tracks(
        file_id="library_files/cold_doc",
        backbone_id=backbone,
        limit=5,
        min_score=0.0,
        nprobe=20,  # explicit nprobe to avoid config lookup in test
    )

    assert [item["file_id"] for item in results] == ["library_files/cold_doc"]


def test_get_track_vector_cold_only(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
) -> None:
    """Vector retrieval reads cold only — returns None when only hot data exists."""

    service = VectorSearchService(cast("Database", fake_database), config_svc=MagicMock())
    backbone = "effnet"
    hot_ops = fake_database.register_vectors_track_backbone(backbone)
    fake_database.get_vectors_track_cold(backbone)  # ensure cold fixture exists

    hot_ops.upsert_vector(
        file_id="library_files/hot_only",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.2, 0.3, 0.4],
        num_segments=1,
    )

    # No cold data — should return None
    assert vector_harness.cold_count(backbone) == 0
    result = service.get_track_vector(backbone, "library_files/hot_only")
    assert result is None

    # After seeding cold, should return the vector
    vector_harness.seed_cold(
        backbone,
        {
            "file_id": "library_files/hot_only",
            "model_suite_hash": "suite",
            "vector": [0.2, 0.3, 0.4],
            "vector_n": [0.2, 0.3, 0.4],
            "embed_dim": 3,
            "num_segments": 1,
        },
    )
    result = service.get_track_vector(backbone, "library_files/hot_only")
    assert result is not None
    assert result["file_id"] == "library_files/hot_only"


def test_cascade_delete_calls_hot_and_cold_ops() -> None:
    """Database.delete_vectors_by_file_id should delete across hot/cold caches."""

    database = object.__new__(Database)

    class _DeleteField:
        def __init__(self, deleted: int) -> None:
            self.deleted = deleted
            self.calls: list[str] = []

        def delete(self, file_id: str) -> int:
            self.calls.append(file_id)
            return self.deleted

    class _VectorNamespace:
        def __init__(self, deleted: int) -> None:
            self.file_id = _DeleteField(deleted)

    hot_namespace = _VectorNamespace(1)
    cold_namespace = _VectorNamespace(2)
    database.vectors_track = cast("dict[str, Any]", {"effnet__lib": hot_namespace})
    database._vectors_track_cold = cast("dict[str, Any]", {"effnet__lib": cold_namespace})
    database.db = MagicMock()

    deleted = Database.delete_vectors_by_file_id(database, "library_files/7")

    assert deleted == 3
    assert hot_namespace.file_id.calls == ["library_files/7"]
    assert cold_namespace.file_id.calls == ["library_files/7"]
    database.db.aql.execute.assert_called_once()
    assert database.db.aql.execute.call_args.kwargs["bind_vars"] == {"file_id": "library_files/7"}


def test_promote_is_safe_no_op_when_hot_empty(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running promote on an empty hot collection should succeed without changes."""

    service = VectorMaintenanceService(cast("Database", fake_database), models_dir="/ml-models", config_svc=MagicMock())
    call_counter = {"count": 0}

    def fake_workflow(**kwargs: Any) -> None:
        call_counter["count"] += 1
        vector_harness.move_hot_to_cold(
            backbone_id=kwargs["backbone_id"],
            nlists=kwargs["nlists"],
        )

    monkeypatch.setattr(
        "nomarr.services.domain.vector_maintenance_svc.promote_and_rebuild_workflow",
        fake_workflow,
    )

    service.promote_and_rebuild("effnet", library_key="test_lib", nlists=24)

    assert call_counter["count"] == 1
    assert vector_harness.hot_count("effnet") == 0
    assert vector_harness.cold_count("effnet") == 0


def test_promote_twice_keeps_cold_collection_convergent(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated promote cycles should not duplicate cold vectors (unique _key)."""

    service = VectorMaintenanceService(cast("Database", fake_database), models_dir="/ml-models", config_svc=MagicMock())

    def fake_workflow(**kwargs: Any) -> None:
        vector_harness.move_hot_to_cold(
            backbone_id=kwargs["backbone_id"],
            nlists=kwargs["nlists"],
        )

    monkeypatch.setattr(
        "nomarr.services.domain.vector_maintenance_svc.promote_and_rebuild_workflow",
        fake_workflow,
    )

    hot_ops = fake_database.register_vectors_track_backbone("effnet")
    hot_ops.upsert_vector(
        file_id="library_files/99",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.3, 0.4, 0.5],
        num_segments=3,
    )
    service.promote_and_rebuild("effnet", library_key="test_lib", nlists=16)

    hot_ops.upsert_vector(
        file_id="library_files/99",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.6, 0.7, 0.8],
        num_segments=3,
    )
    service.promote_and_rebuild("effnet", library_key="test_lib", nlists=16)

    assert vector_harness.cold_count("effnet") == 1
    stored = vector_harness.get_cold_vector("effnet", "library_files/99")
    assert stored is not None
    assert stored["vector"] == [0.6, 0.7, 0.8]
    assert stored["vector"] == [0.6, 0.7, 0.8]
