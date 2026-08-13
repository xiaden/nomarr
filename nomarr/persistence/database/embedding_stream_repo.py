"""EmbeddingStreamRepository — CRUD for the ``ml_embedding_streams`` table.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
upserts and filtered queries.

Field mapping note:
    The DTO field ``backbone`` maps to the model column ``backbone_id``.
    The model has no ``updated_at`` column; the DTO field ``updated_at``
    is always ``None``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, select, update

from nomarr.helpers.dto.embedding_stream_repo_dto import EmbeddingStreamRecord
from nomarr.persistence.models.ml_embedding_stream import MlEmbeddingStream
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", MlEmbeddingStream.__table__)


def _row_to_dto(row: Row[Any]) -> EmbeddingStreamRecord:
    """Convert a SQLAlchemy ``Row`` to an ``EmbeddingStreamRecord`` TypedDict.

    Field mapping:
        - ``backbone`` DTO field ← ``backbone_id`` model column
        - ``updated_at`` DTO field ← ``None`` (model has no updated_at column)
    """
    m = row._mapping
    return EmbeddingStreamRecord(
        id=m["id"],
        song_id=m["song_id"],
        backbone=m["backbone_id"],
        patches_emb=m["patches_emb"],
        created_at=m["created_at"],
        updated_at=None,
    )


class EmbeddingStreamRepository:
    """Repository for the ``ml_embedding_streams`` table."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    def upsert_stream(
        self,
        song_id: int,
        backbone: str,
        stream_payload: dict[str, Any],
    ) -> EmbeddingStreamRecord:
        """Insert or update an embedding stream for a (song, backbone) pair.

        ``ml_embedding_streams`` has no unique constraint on
        ``(song_id, backbone_id)``, so this uses a select-then-insert-or-update
        pattern.  ``patches_emb`` is extracted from *stream_payload*.
        """
        with map_persistence_exceptions():
            patches_emb: bytes = stream_payload["patches_emb"]
            existing = self._get_existing(song_id, backbone)

            if existing is not None:
                with self._session.begin_nested():
                    stmt = update(_T).where(_T.c.id == existing["id"]).values(patches_emb=patches_emb).returning(_T)
                    result = self._session.execute(stmt)
                    row = result.fetchone()
                self._session.commit()
                assert row is not None
                return _row_to_dto(row)

            now = int(time.time())
            with self._session.begin_nested():
                row = insert_one(
                    _T,
                    {
                        "song_id": song_id,
                        "backbone_id": backbone,
                        "patches_emb": patches_emb,
                        "created_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_dto(row)

    def get_stream(self, song_id: int, backbone: str) -> EmbeddingStreamRecord | None:
        """Fetch the embedding stream for a (song, backbone) pair."""
        with map_persistence_exceptions():
            return self._get_existing(song_id, backbone)

    def list_by_backbone(
        self,
        backbone: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[EmbeddingStreamRecord]:
        """Return embedding streams for a backbone, ordered by ``id``.

        Supports optional pagination via *limit* and *offset*.
        """
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.backbone_id == backbone).order_by(_T.c.id)
            if offset:
                stmt = stmt.offset(offset)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_row_to_dto(r) for r in result.all()]

    def delete_for_song(self, song_id: int) -> None:
        """Delete all embedding streams for a given song."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.song_id == song_id)
                self._session.execute(stmt)
            self._session.commit()

    # ── internal helpers ────────────────────────────────────────

    def _get_existing(self, song_id: int, backbone: str) -> EmbeddingStreamRecord | None:
        """Fetch the stream row for a (song, backbone) pair, as a DTO."""
        stmt = select(_T).where(
            _T.c.song_id == song_id,
            _T.c.backbone_id == backbone,
        )
        result = self._session.execute(stmt)
        row = result.fetchone()
        return _row_to_dto(row) if row else None
