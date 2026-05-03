"""Domain-specific vector collection registry.

Wraps `db.register()` to resolve hot/cold/maintenance namespaces by
backbone+library, and owns batch vector deletion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.constructor.namespaces import VectorsTrackMaintenanceNamespace

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.persistence.stubs.vectors_track import (
        VectorsTrackColdNamespace,
        VectorsTrackHotNamespace,
        VectorsTrackMaintenanceProtocol,
    )


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
        VectorsTrackMaintenanceNamespace(
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

    for namespace in db._template_namespaces.values():
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

    for namespace in db._template_namespaces.values():
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
