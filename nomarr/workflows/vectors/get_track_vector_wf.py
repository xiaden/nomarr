"""Retrieve a track's normalized embedding vector.

Fetches the promoted (cold-tier) vector for a semantic song locator
through :func:`nomarr.components.ml.vectors.ml_vector_retrieve_comp.get_cold_track_vector`,
returning a domain :class:`SongVector` carrying the actual stored embedding.
Transport identity/response adaptation to ``VectorGetResponse`` happens at the
service/HTTP boundary, never here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import get_cold_track_vector

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.vector_dataclass import SongVector
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_track_vector(
    db: Database,
    song: SongIdentity,
    backbone_id: str,
) -> SongVector | None:
    """Get a track's promoted vector by semantic locator and backbone.

    Args:
        db: Database instance.
        song: Semantic ``SongIdentity`` locator.
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        A :class:`SongVector` carrying the actual stored embedding, or ``None``
        when the backbone has no cold
        embeddings, or the song has no promoted vector.

    """
    return get_cold_track_vector(db, song, backbone_id)
