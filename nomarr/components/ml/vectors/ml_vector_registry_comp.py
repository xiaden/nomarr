"""Domain-specific vector collection registry.

Wraps `db.ml.add_vector_collection()` to resolve hot/cold/maintenance
namespaces by backbone+library, and owns batch vector deletion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _FieldDeleteProtocol(Protocol):
    def __call__(self, value: Any) -> int: ...

    def in_(self, values: list[Any]) -> int: ...


class _FieldDeleteAccessorProtocol(Protocol):
    delete: _FieldDeleteProtocol


class VectorsTrackHotNamespace(Protocol):
    """Typed surface used by hot vector namespace callers."""

    file_id: _FieldDeleteAccessorProtocol

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

    def move_collection(self, dest: str) -> int: ...


class VectorsTrackColdNamespace(Protocol):
    """Typed surface used by cold vector namespace callers."""

    file_id: _FieldDeleteAccessorProtocol

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


class VectorsTrackMaintenanceProtocol(Protocol):
    """Protocol for maintenance operations spanning hot/cold vector collections."""

    def drop_index(self) -> None: ...

    def build_index(self, *, embed_dim: int, nlists: int) -> None: ...

    def rebuild_index(self, *, embed_dim: int, nlists: int) -> None: ...

    def get_stats(self) -> dict[str, int | bool]: ...


__all__ = [
    "delete_vectors_by_file_id",
    "delete_vectors_by_file_ids",
    "get_cold_namespace",
    "get_hot_namespace",
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
        Exception: Propagates errors raised by ``db.ml.add_vector_collection()``
            while resolving the namespace.
    """
    col_name = f"vectors_track_hot__{backbone_id}__{library_key}"
    return cast("VectorsTrackHotNamespace", db.ml.add_vector_collection(col_name, "vectors_track_hot"))


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
        Exception: Propagates errors raised by ``db.ml.add_vector_collection()``
            while resolving the namespace.
    """
    col_name = f"vectors_track_cold__{backbone_id}__{library_key}"
    if collection_suffix:
        col_name = f"{col_name}__{collection_suffix}"
    return cast("VectorsTrackColdNamespace", db.ml.add_vector_collection(col_name, "vectors_track_cold"))


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
    registered_collections = cast("dict[str, Any]", db.ml.list_vector_namespaces())

    for collection_name in registered_collections:
        total_deleted += len(db.ml.list_file_vectors(collection_name, file_id))
        db.ml.remove_file_vectors(collection_name, file_id)

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
    registered_collections = cast("dict[str, Any]", db.ml.list_vector_namespaces())

    for collection_name in registered_collections:
        for file_id in file_ids:
            total_deleted += len(db.ml.list_file_vectors(collection_name, file_id))
        db.ml.remove_vectors_for_files(collection_name, file_ids)

    return total_deleted
