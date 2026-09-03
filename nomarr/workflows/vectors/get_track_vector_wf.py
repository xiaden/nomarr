"""Retrieve a track's normalized embedding vector.

Resolves the requested file handle and fetches the promoted (cold-tier) vector
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
    from nomarr.helpers.dataclasses.vector_dataclass import SongVector
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def get_track_vector(
    db: Database,
    file_id: int,
    backbone_id: str,
) -> SongVector | None:
    """Get a track's promoted vector by file handle and backbone.

    Single step: the component resolves the ``file_id`` to a natural
    :class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity`
    through ``db.library`` and reads the cold-tier stored vector.

    Args:
        db: Database instance.
        file_id: Library song handle (file id).
        backbone_id: Backbone identifier (e.g. ``"effnet"``).

    Returns:
        A :class:`SongVector` carrying the actual stored embedding, or ``None``
        when the file handle does not resolve, the backbone has no cold
        embeddings, or the song has no promoted vector.

    """
    return get_cold_track_vector(db, file_id, backbone_id)
