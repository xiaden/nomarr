"""Domain-specific vector operations.

Provides batch vector deletion backed by the ``db.ml.*`` PostgreSQL API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


__all__ = [
    "delete_vectors_by_file_id",
    "delete_vectors_by_file_ids",
]


async def delete_vectors_by_file_id(db: Database, file_id: str) -> int:
    """Delete vectors for a file from every registered vector collection.

    Args:
        db: Database façade.
        file_id: Document identifier used by registered vector namespaces.
            Converted to ``int`` for the PostgreSQL API.

    Returns:
        Total number of vector documents deleted across all registered
        collections.

    """
    total_deleted = 0
    collection_names = db.ml.list_vector_collection_names()

    for collection_name in collection_names:
        vectors = await db.ml.list_file_vectors(collection_name, int(file_id))
        total_deleted += len(vectors)
        await db.ml.remove_file_vectors(collection_name, int(file_id))

    return total_deleted


async def delete_vectors_by_file_ids(db: Database, file_ids: list[str]) -> int:
    """Delete vectors for multiple files from every registered vector collection.

    Args:
        db: Database façade.
        file_ids: Document identifiers used by registered vector namespaces.
            Each value is converted to ``int`` for the PostgreSQL API.

    Returns:
        Total number of vector documents deleted across all registered
        collections.  Returns ``0`` if ``file_ids`` is empty.

    """
    if not file_ids:
        return 0

    total_deleted = 0
    collection_names = db.ml.list_vector_collection_names()

    for collection_name in collection_names:
        for file_id in file_ids:
            vectors = await db.ml.list_file_vectors(collection_name, int(file_id))
            total_deleted += len(vectors)
        int_file_ids = [int(fid) for fid in file_ids]
        await db.ml.remove_vectors_for_files(collection_name, int_file_ids)

    return total_deleted
