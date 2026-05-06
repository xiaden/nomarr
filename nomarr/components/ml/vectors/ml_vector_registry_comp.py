"""Domain-specific vector collection registry.

Wraps `db.register()` to resolve hot/cold/maintenance namespaces by
backbone+library, and owns batch vector deletion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

from nomarr.persistence.arango_client import SafeDatabase

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _VectorFileIdDeleteProtocol(Protocol):
    """Protocol for vector namespaces exposing ``file_id.delete()``."""

    def delete(self, value: str) -> int: ...


class VectorsTrackHotNamespace(Protocol):
    """Typed surface used by hot vector namespace callers."""

    file_id: _VectorFileIdDeleteProtocol

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None: ...

    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]: ...

    def count(self) -> int: ...

    def truncate(self) -> None: ...

    def delete_by_file_id(self, file_id: str) -> int: ...

    def delete_by_file_ids(self, file_ids: list[str]) -> int: ...

    def move_collection(self, dest: str) -> int: ...


class VectorsTrackColdNamespace(Protocol):
    """Typed surface used by cold vector namespace callers."""

    file_id: _VectorFileIdDeleteProtocol

    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]: ...

    def count(self) -> int: ...

    def ann_search(
        self,
        vector: list[float],
        limit: int,
        nprobe: int = 10,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def delete_by_file_id(self, file_id: str) -> int: ...

    def delete_by_file_ids(self, file_ids: list[str]) -> int: ...


class VectorsTrackMaintenanceProtocol(Protocol):
    """Protocol for maintenance operations spanning hot/cold vector collections."""

    def drop_index(self) -> None: ...

    def build_index(self, *, embed_dim: int, nlists: int) -> None: ...

    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None: ...

    def get_stats(self) -> dict[str, int | bool]: ...


class _VectorsTrackMaintenance:
    """Maintenance operations spanning a vectors_track hot/cold collection pair."""

    def __init__(self, db: SafeDatabase, hot_collection_name: str, cold_collection_name: str) -> None:
        self._db = db
        self._hot_collection_name = hot_collection_name
        self._cold_collection_name = cold_collection_name

    def drop_index(self) -> None:
        """Drop the cold collection vector index if it exists."""
        if not self._db.has_collection(self._cold_collection_name):
            msg = f"Cold collection '{self._cold_collection_name}' does not exist"
            raise ValueError(msg)

        cold_collection = self._db.collection(self._cold_collection_name)
        existing_indexes = cast("list[dict[str, Any]]", cold_collection.indexes())
        for index in existing_indexes:
            if index.get("type") == "vector" and index.get("id"):
                cold_collection.delete_index(index["id"])

    def build_index(self, *, embed_dim: int, nlists: int) -> None:
        """Create the cold collection vector index."""
        if not self._db.has_collection(self._cold_collection_name):
            msg = f"Cold collection '{self._cold_collection_name}' does not exist"
            raise ValueError(msg)

        cold_collection = self._db.collection(self._cold_collection_name)
        cold_collection.add_index(
            {
                "type": "vector",
                "fields": ["vector_n"],
                "params": {
                    "metric": "cosine",
                    "dimension": embed_dim,
                    "nLists": nlists,
                },
                "storedValues": ["genres"],
            }
        )

    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None:
        """Drop and rebuild the cold collection vector index."""
        self.drop_index()
        self.build_index(embed_dim=embed_dim, nlists=nlists)

    def get_stats(self) -> dict[str, int | bool]:
        """Return current hot/cold counts and cold-index state."""
        hot_count = 0
        if self._db.has_collection(self._hot_collection_name):
            hot_count = cast("int", self._db.collection(self._hot_collection_name).count())

        cold_count = 0
        index_exists = False
        if self._db.has_collection(self._cold_collection_name):
            cold_collection = self._db.collection(self._cold_collection_name)
            cold_count = cast("int", cold_collection.count())
            existing_indexes = cast("list[dict[str, Any]]", cold_collection.indexes())
            index_exists = any(index.get("type") == "vector" for index in existing_indexes)

        return {
            "hot_count": hot_count,
            "cold_count": cold_count,
            "index_exists": index_exists,
        }


__all__ = [
    "delete_vectors_by_file_id",
    "delete_vectors_by_file_ids",
    "get_cold_namespace",
    "get_hot_namespace",
    "get_maintenance_namespace",
]


def get_hot_namespace(db: Database, backbone_id: str, library_key: str) -> VectorsTrackHotNamespace:
    """Resolve the hot vectors namespace for a backbone/library pair.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier used to namespace vector collections.
        library_key: Library ``_key`` used to namespace vector collections.

    Returns:
        Registered hot vectors namespace for the ``backbone_id`` and ``library_key`` pair.

    Raises:
        Exception: Propagates errors raised by ``db.register()`` while resolving the
            namespace.
    """
    col_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    return cast("VectorsTrackHotNamespace", db.register(col_name, "vectors_track_hot"))


def get_cold_namespace(
    db: Database,
    backbone_id: str,
    library_key: str,
    collection_suffix: str | None = None,
) -> VectorsTrackColdNamespace:
    """Resolve the cold vectors namespace for a backbone/library pair.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier used to namespace vector collections.
        library_key: Library ``_key`` used to namespace vector collections.
        collection_suffix: Optional suffix appended to the resolved collection name
            when provided.

    Returns:
        Registered cold vectors namespace for the ``backbone_id`` and ``library_key``
        pair, with ``collection_suffix`` appended to the collection name when set.

    Raises:
        Exception: Propagates errors raised by ``db.register()`` while resolving the
            namespace.
    """
    col_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if collection_suffix:
        col_name = f"{col_name}__{collection_suffix}"
    return cast("VectorsTrackColdNamespace", db.register(col_name, "vectors_track_cold"))


def get_maintenance_namespace(
    db: Database,
    backbone_id: str,
    library_key: str,
) -> VectorsTrackMaintenanceProtocol:
    """Build a maintenance namespace for the vectors hot/cold collection pair.

    Args:
        db: Database façade.
        backbone_id: Backbone identifier used to derive the paired collection names.
        library_key: Library ``_key`` used to derive the paired collection names.

    Returns:
        Maintenance namespace wrapping the resolved hot and cold vector collection
        pair for the ``backbone_id`` and ``library_key``.

    Raises:
        Exception: Propagates database errors encountered while constructing the
            maintenance namespace.
    """
    return cast(
        "VectorsTrackMaintenanceProtocol",
        _VectorsTrackMaintenance(
            db.db,
            hot_collection_name=f"vectors_track_hot__{backbone_id}__{library_key}",
            cold_collection_name=f"vectors_track_cold__{backbone_id}__{library_key}",
        ),
    )


def delete_vectors_by_file_id(db: Database, file_id: str) -> int:
    """Delete vectors for a file from every registered template namespace.

    Args:
        db: Database façade.
        file_id: Document identifier used by registered vector namespaces and the
            ``file_has_vectors`` edge collection.

    Returns:
        Total number of vector documents deleted across all registered namespaces.
        Also removes matching edges from ``file_has_vectors``.

    Raises:
        Exception: Propagates database errors raised while deleting vectors or
            removing ``file_has_vectors`` edges.
    """
    total_deleted = 0
    registered_collections = cast("dict[str, Any]", getattr(db, "_registered", {}))

    for namespace in registered_collections.values():
        deleted = cast("VectorsTrackHotNamespace", namespace).file_id.delete(file_id)
        total_deleted += deleted

    db.db.aql.execute(
        """
        FOR e IN file_has_vectors
            FILTER e._from == @file_id
            REMOVE e IN file_has_vectors
        """,
        bind_vars={"file_id": file_id},
    )

    return total_deleted


def delete_vectors_by_file_ids(db: Database, file_ids: list[str]) -> int:
    """Delete vectors for multiple files from every registered template namespace.

    Args:
        db: Database façade.
        file_ids: Document identifiers used by registered vector namespaces and the
            ``file_has_vectors`` edge collection.

    Returns:
        Total number of vector documents deleted across all registered namespaces.
        Returns ``0`` if ``file_ids`` is empty. Also removes matching edges from
        ``file_has_vectors``.

    Raises:
        Exception: Propagates database errors raised while deleting vectors or
            removing ``file_has_vectors`` edges.
    """
    if not file_ids:
        return 0

    total_deleted = 0
    registered_collections = cast("dict[str, Any]", getattr(db, "_registered", {}))

    for namespace in registered_collections.values():
        typed_namespace = cast("VectorsTrackHotNamespace", namespace)
        for file_id in file_ids:
            total_deleted += typed_namespace.file_id.delete(file_id)

    db.db.aql.execute(
        """
        FOR e IN file_has_vectors
            FILTER e._from IN @file_ids
            REMOVE e IN file_has_vectors
        """,
        bind_vars=cast("dict[str, Any]", {"file_ids": file_ids}),
    )

    return total_deleted
