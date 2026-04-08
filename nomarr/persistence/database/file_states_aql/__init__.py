"""File state edge operations for ArangoDB."""

from __future__ import annotations

from typing import Any

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import (
    _EDGE_COLLECTION,
    ALL_STATE_VERTICES,
    AXIS_PAIRS,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_SCANNED,
    STATE_NOT_TAGGED,
    STATE_NOT_TOO_SHORT,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_SCANNED,
    STATE_TAGGED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_STALE,
    STATE_TAGS_WRITTEN,
    STATE_TOO_SHORT,
    STATE_VECTORS_EXTRACTED,
)
from .bulk import FileStatesBulkMixin
from .init import FileStatesInitMixin
from .queries import FileStatesQueriesMixin
from .reset import FileStatesResetMixin
from .transitions import FileStatesTransitionsMixin


class FileStatesOperations(
    FileStatesTransitionsMixin,
    FileStatesBulkMixin,
    FileStatesInitMixin,
    FileStatesQueriesMixin,
    FileStatesResetMixin,
):
    """CRUD operations for the ``file_has_state`` edge collection."""

    db: DatabaseLike
    collection: Any

    def __init__(self, db: DatabaseLike) -> None:
        """Initialise operations against the given database connection."""
        self.db = db
        self.collection = db.collection(_EDGE_COLLECTION)  # type: ignore[union-attr]


__all__ = [
    "ALL_STATE_VERTICES",
    "AXIS_PAIRS",
    "STATE_CALIBRATED",
    "STATE_ERRORED",
    "STATE_NOT_CALIBRATED",
    "STATE_NOT_ERRORED",
    "STATE_NOT_SCANNED",
    "STATE_NOT_TAGGED",
    "STATE_NOT_TOO_SHORT",
    "STATE_NOT_VECTORS_EXTRACTED",
    "STATE_SCANNED",
    "STATE_TAGGED",
    "STATE_TAGS_CURRENT",
    "STATE_TAGS_NOT_WRITTEN",
    "STATE_TAGS_STALE",
    "STATE_TAGS_WRITTEN",
    "STATE_TOO_SHORT",
    "STATE_VECTORS_EXTRACTED",
    "FileStatesOperations",
]
