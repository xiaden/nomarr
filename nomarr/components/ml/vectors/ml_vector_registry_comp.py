"""Domain-specific vector operations.

Provides batch vector deletion backed by the ``db.ml.*`` PostgreSQL API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


__all__ = [
    "delete_vectors_by_song_id",
    "delete_vectors_by_song_ids",
]


def delete_vectors_by_song_id(db: Database, song_id: str) -> int:
    """Delete vectors for a song from every registered vector collection.

    Args:
        db: Database façade.
        song_id: Document identifier used by registered vector namespaces.
            Converted to ``int`` for the PostgreSQL API.

    Returns:
        Total number of vector documents deleted across all registered
        collections.

    """
    total_deleted = 0
    collection_names = db.ml.list_vector_collection_names()

    for collection_name in collection_names:
        vectors = db.ml.list_song_vectors(collection_name, int(song_id))
        total_deleted += len(vectors)
        db.ml.remove_song_vectors(collection_name, int(song_id))

    return total_deleted


def delete_vectors_by_song_ids(db: Database, song_ids: list[str]) -> int:
    """Delete vectors for multiple songs from every registered vector collection.

    Args:
        db: Database façade.
        song_ids: Document identifiers used by registered vector namespaces.
            Each value is converted to ``int`` for the PostgreSQL API.

    Returns:
        Total number of vector documents deleted across all registered
        collections.  Returns ``0`` if ``song_ids`` is empty.

    """
    if not song_ids:
        return 0

    total_deleted = 0
    collection_names = db.ml.list_vector_collection_names()

    for collection_name in collection_names:
        for song_id in song_ids:
            vectors = db.ml.list_song_vectors(collection_name, int(song_id))
            total_deleted += len(vectors)
        int_song_ids = [int(sid) for sid in song_ids]
        db.ml.remove_vectors_for_songs(collection_name, int_song_ids)

    return total_deleted
