"""Retrieve and search promoted track embeddings from cold vector stores.

These components are the cold-only vector read helpers shared by the vector
service/workflow consumers.  They resolve integer file handles to a natural
:class:`SongIdentity` through authoritative ``db.library`` before calling the
typed ``db.ml`` read intents, and they return the caller-facing domain values
(:class:`SongVector` / :class:`VectorMatch`) — never raw persistence rows or
storage keys.  Hot collections are write-only accumulation tiers and must
never be searched; only cold (promoted) tiers are read here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_cold_track_vector(
    db: Database,
    file_id: int,
    backbone_id: str,
) -> SongVector | None:
    """Fetch a track's promoted vector from the cold tier.

    Short-circuits when the backbone has no cold embeddings (empty-cold
    optimization), resolves ``file_id`` to a natural :class:`SongIdentity`
    through ``db.library``, then reads the single cold-tier stored vector via
    ``db.ml.get_song_vector``.

    Args:
        db: Database instance.
        file_id: Library song handle (file id).
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        A :class:`SongVector` carrying the actual stored embedding, or ``None``
        when the backbone has no cold embeddings, the file handle does not
        resolve to a library song, or the song has no promoted vector.

    """
    counts = db.ml.embedding_counts(backbone_id)
    if counts.cold_count <= 0:
        logger.debug(
            "[vectors] Cold tier is empty for backbone=%s",
            backbone_id,
        )
        return None

    song = db.library.resolve_song_identity(file_id)
    if song is None:
        return None

    return db.ml.get_song_vector(backbone_id, song)


def search_similar_cold_track_vectors(
    db: Database,
    backbone_id: str,
    seed_vector: Sequence[float],
    result_limit: int,
    *,
    include_vector: bool = False,
) -> tuple[VectorMatch, ...]:
    """Run ANN similarity search against the promoted cold tier.

    Short-circuits when the cold tier is empty.  Delegates to the typed
    ``db.ml.search_similar_vectors`` intent; vector payloads are included only
    when ``include_vector`` is explicit.

    Args:
        db: Database instance.
        backbone_id: Backbone identifier used to select the cold namespace.
        seed_vector: Query embedding vector used as the ANN search seed.
        result_limit: Maximum number of similar matches to return.
        include_vector: Whether each returned :class:`VectorMatch` carries its
            stored vector (``False`` by default).

    Returns:
        Ordered tuple of :class:`VectorMatch` matches.  Returns an empty tuple
        when the promoted cold tier contains no embeddings.

    """
    counts = db.ml.embedding_counts(backbone_id)
    if counts.cold_count <= 0:
        logger.debug(
            "Skipping ANN search because cold tier is empty for backbone=%s",
            backbone_id,
        )
        return ()

    return db.ml.search_similar_vectors(
        backbone_id,
        seed_vector,
        limit=result_limit,
        include_vector=include_vector,
    )
