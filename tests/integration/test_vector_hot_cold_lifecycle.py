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
        key = doc.get("_key") or _make_vector_key(
            doc["file_id"], doc.get("model_suite_hash", "default")
        )
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
        candidates = [
            doc
            for doc in self.hot_docs[backbone_id].values()
            if doc["file_id"] == file_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda doc: doc["created_at"])

    def get_cold_vector(self, backbone_id: str, file_id: str) -> dict[str, Any] | None:
        candidates = [
            doc
            for doc in self.cold_docs[backbone_id].values()
            if doc["file_id"] == file_id
        ]
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

    def indexes(self) -> list[dict[str, Any]]:
        if "vectors_track_cold__" in self.name:
            backbone = self.name.split("__", maxsplit=1)[1]
            if self.harness.has_vector_index(backbone):
                return [{"type": "vector"}]
        return []

    def truncate(self) -> None:
        backbone = self.name.split("__", maxsplit=1)[1]
        if "vectors_track_hot__" in self.name:
            self.harness.hot_docs[backbone].clear()
        else:
            self.harness.cold_docs[backbone].clear()


class FakeArangoHandle:
    """Surface has_collection/collection methods expected by services."""

    def __init__(self, harness: VectorLifecycleHarness) -> None:
        self.harness = harness

    def has_collection(self, name: str) -> bool:
        if "vectors_track_hot__" in name:
            backbone = name.split("__", maxsplit=1)[1]
            return backbone in self.harness.known_backbones
        if "vectors_track_cold__" in name:
            backbone = name.split("__", maxsplit=1)[1]
            return backbone in self.harness.cold_collections
        return False

    def collection(self, name: str) -> FakeArangoCollection:
        return FakeArangoCollection(self.harness, name)


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

    def search_similar(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        return self.harness.search_cold(self.backbone_id, vector, limit)

    def count(self) -> int:
        return self.harness.cold_count(self.backbone_id)

    def delete_by_file_id(self, file_id: str) -> int:
        return self.harness.delete_cold(self.backbone_id, file_id)

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        return sum(self.delete_by_file_id(file_id) for file_id in file_ids)


class FakeDatabaseAdapter:
    """Provides the minimal Database interface needed by the services."""

    def __init__(self, harness: VectorLifecycleHarness) -> None:
        self.harness = harness
        self.db = FakeArangoHandle(harness)
        self.vectors_track: dict[str, FakeHotOperations] = {}
        self._vectors_track_cold: dict[str, FakeColdOperations] = {}

    def register_vectors_track_backbone(self, backbone_id: str) -> FakeHotOperations:
        self.harness.register_backbone(backbone_id)
        return self.vectors_track.setdefault(
            backbone_id, FakeHotOperations(self.harness, backbone_id)
        )

    def get_vectors_track_cold(self, backbone_id: str) -> FakeColdOperations:
        self.harness.ensure_cold_collection(backbone_id)
        return self._vectors_track_cold.setdefault(
            backbone_id, FakeColdOperations(self.harness, backbone_id)
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
    db_mock.has_collection.return_value = False
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
        "nomarr.components.platform.arango_bootstrap_comp._discover_backbone_ids",
        lambda _models_dir: ["effnet", "yamnet"],
    )
    monkeypatch.setattr(
        "nomarr.components.platform.arango_bootstrap_comp._ensure_index",
        record_index,
    )

    _create_vectors_track_collections(db_mock, models_dir="/tmp/models")

    assert created_collections == [
        "vectors_track_hot__effnet",
        "vectors_track_hot__yamnet",
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

    service = VectorMaintenanceService(
        cast("Database", fake_database), models_dir="/ml-models"
    )
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

    service.promote_and_rebuild("effnet", nlists=48)

    assert vector_harness.hot_count("effnet") == 0
    assert vector_harness.cold_count("effnet") == 1
    assert vector_harness.has_vector_index("effnet")


def test_search_similar_uses_cold_only(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
) -> None:
    """Similarity search must ignore hot data and honor cold-only semantics."""

    service = VectorSearchService(cast("Database", fake_database))
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

    vector_harness.seed_cold(
        backbone,
        {
            "file_id": "library_files/cold_doc",
            "model_suite_hash": "suite",
            "vector": [0.1, 0.9, 0.2],
            "embed_dim": 3,
            "num_segments": 2,
        },
    )
    vector_harness.install_vector_index(backbone)

    results = service.search_similar_tracks(
        backbone_id=backbone,
        vector=[0.1, 0.8, 0.2],
        limit=5,
        min_score=0.0,
    )

    assert [item["file_id"] for item in results] == ["library_files/cold_doc"]


def test_get_track_vector_falls_back_to_hot(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
) -> None:
    """Direct vector retrieval should read hot when cold misses the file."""

    service = VectorSearchService(cast("Database", fake_database))
    backbone = "effnet"
    hot_ops = fake_database.register_vectors_track_backbone(backbone)

    hot_ops.upsert_vector(
        file_id="library_files/404",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.2, 0.3, 0.4],
        num_segments=1,
    )

    assert vector_harness.cold_count(backbone) == 0
    result = service.get_track_vector(backbone, "library_files/404")
    assert result is not None
    assert result["file_id"] == "library_files/404"


def test_cascade_delete_calls_hot_and_cold_ops() -> None:
    """Database.delete_vectors_by_file_id should delete across hot/cold caches."""

    database = object.__new__(Database)
    hot_ops = MagicMock()
    cold_ops = MagicMock()
    hot_ops.delete_by_file_id.return_value = 1
    cold_ops.delete_by_file_id.return_value = 2

    database.vectors_track = {"effnet": hot_ops}
    database._vectors_track_cold = {"effnet": cold_ops}

    deleted = Database.delete_vectors_by_file_id(database, "library_files/7")

    assert deleted == 3
    hot_ops.delete_by_file_id.assert_called_once_with("library_files/7")
    cold_ops.delete_by_file_id.assert_called_once_with("library_files/7")


def test_promote_is_safe_no_op_when_hot_empty(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running promote on an empty hot collection should succeed without changes."""

    service = VectorMaintenanceService(
        cast("Database", fake_database), models_dir="/ml-models"
    )
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

    service.promote_and_rebuild("effnet", nlists=24)

    assert call_counter["count"] == 1
    assert vector_harness.hot_count("effnet") == 0
    assert vector_harness.cold_count("effnet") == 0


def test_promote_twice_keeps_cold_collection_convergent(
    fake_database: FakeDatabaseAdapter,
    vector_harness: VectorLifecycleHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated promote cycles should not duplicate cold vectors (unique _key)."""

    service = VectorMaintenanceService(
        cast("Database", fake_database), models_dir="/ml-models"
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

    hot_ops = fake_database.register_vectors_track_backbone("effnet")
    hot_ops.upsert_vector(
        file_id="library_files/99",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.3, 0.4, 0.5],
        num_segments=3,
    )
    service.promote_and_rebuild("effnet", nlists=16)

    hot_ops.upsert_vector(
        file_id="library_files/99",
        model_suite_hash="suite",
        embed_dim=3,
        vector=[0.6, 0.7, 0.8],
        num_segments=3,
    )
    service.promote_and_rebuild("effnet", nlists=16)

    assert vector_harness.cold_count("effnet") == 1
    stored = vector_harness.get_cold_vector("effnet", "library_files/99")
    assert stored is not None
    assert stored["vector"] == [0.6, 0.7, 0.8]
