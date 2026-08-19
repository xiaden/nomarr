"""VectorRepo — embedding storage and ANN search for the ``embeddings`` table.

Uses SQLAlchemy Core against the single ``embeddings`` table with pgvector
``<=>`` operator for approximate nearest-neighbour search on cold-tier
embeddings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, insert, select, text, update

from nomarr.helpers.dto.vector_repo_dto import EmbeddingRecord, SimilarResult
from nomarr.helpers.time_helper import now_ms
from nomarr.helpers.vector_params_helper import get_ef_search
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.sql.exceptions import map_persistence_exceptions

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_T = cast("Table", Embedding.__table__)


def _row_to_embedding_record(row: Row[Any]) -> EmbeddingRecord:
    """Convert a SQLAlchemy ``Row`` to an ``EmbeddingRecord`` TypedDict."""
    m = row._mapping
    return EmbeddingRecord(
        id=m["id"],
        song_id=m["song_id"],
        backbone_id=m["backbone_id"],
        tier=m["tier"],
        embed_dim=m["embed_dim"],
        model_suite_hash=m["model_suite_hash"],
        num_segments=m["num_segments"],
        segmentation_hash=m["segmentation_hash"],
        genres=m["genres"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def _row_to_similar_result(row: Row[Any]) -> SimilarResult:
    """Convert a SQLAlchemy ``Row`` to a ``SimilarResult`` TypedDict."""
    m = row._mapping
    return SimilarResult(
        song_id=m["song_id"],
        backbone_id=m["backbone_id"],
        distance=m["distance"],
    )


class VectorRepo:
    """Repository for the ``embeddings`` table.

    Provides embedding insert, ANN similarity search, hot/cold tier
    lifecycle management, and maintenance operations (delete/truncate).
    """

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── insert ──────────────────────────────────────────────────

    def insert_embedding(
        self,
        song_id: int,
        backbone_id: str,
        model_id: str,
        embedding_vector: list[float],
        genres: list[str] | None = None,
    ) -> EmbeddingRecord:
        """Insert an embedding row with ``tier='hot'``.

        ``embed_dim`` is computed automatically from *embedding_vector*.
        ``model_suite_hash`` is set to ``""`` (NOT NULL placeholder) —
        populated later by the model-suite tracking pipeline.
        ``num_segments`` and ``segmentation_hash`` are ``None`` — populated
        later by the segmentation analysis pipeline.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                now = now_ms().value
                stmt = (
                    insert(_T)
                    .values(
                        song_id=song_id,
                        backbone_id=backbone_id,
                        model_id=model_id,
                        embed_dim=len(embedding_vector),
                        model_suite_hash="",
                        num_segments=None,
                        segmentation_hash=None,
                        embedding=embedding_vector,
                        genres=genres,
                        tier="hot",
                        created_at=now,
                        updated_at=now,
                    )
                    .returning(_T)
                )
                result = self._session.execute(stmt)
                row = result.fetchone()
            self._session.commit()
            assert row is not None  # RETURNING always yields a row on success
            return _row_to_embedding_record(row)

    # ── ANN search ──────────────────────────────────────────────

    def find_nearest(
        self,
        embedding: list[float],
        backbone_id: str,
        limit: int = 10,
        ef_search: int | None = None,
    ) -> list[SimilarResult]:
        """Approximate nearest-neighbour search using pgvector ``<=>``.

        Sets session-level ``hnsw.iterative_scan = strict_order`` and
        ``hnsw.ef_search`` for accurate distance ordering.  Only searches
        cold-tier embeddings (the partial HNSW index covers ``tier='cold'``
        rows only).

        Args:
            embedding: Query embedding vector.
            backbone_id: Backbone identifier to filter cold-tier rows.
            limit: Maximum number of results to return (default: 10).
            ef_search: HNSW query-time search width.  When ``None``, computed
                via :func:`~nomarr.helpers.vector_params_helper.get_ef_search`
                with a medium-collection default.

        """
        with map_persistence_exceptions():
            if ef_search is None:
                ef_search = get_ef_search(0)  # sensible default for unknown size
            self._session.execute(text("SET LOCAL hnsw.iterative_scan = 'strict_order'"))
            self._session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef_search)}"))

            distance_expr = _T.c.embedding.op("<=>")(embedding)
            stmt = (
                select(
                    _T.c.song_id,
                    _T.c.backbone_id,
                    distance_expr.label("distance"),
                )
                .where(
                    _T.c.tier == "cold",
                    _T.c.backbone_id == backbone_id,
                )
                .order_by(distance_expr)
                .limit(limit)
            )
            result = self._session.execute(stmt)
            return [_row_to_similar_result(r) for r in result.all()]

    # ── tier lifecycle ──────────────────────────────────────────

    def drain_hot_to_cold(self, backbone_id: str) -> int:
        """Move all hot-tier embeddings to cold for a given backbone.

        Single UPDATE statement — no document copying.  The partial HNSW
        index picks up newly-cold rows on next VACUUM.  Returns the
        number of rows updated.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                now = now_ms().value
                stmt = (
                    update(_T)
                    .where(
                        _T.c.backbone_id == backbone_id,
                        _T.c.tier == "hot",
                    )
                    .values(tier="cold", updated_at=now)
                )
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult.rowcount is int at runtime

    # ── queries ─────────────────────────────────────────────────

    def get_embeddings_for_song(self, song_id: int) -> list[EmbeddingRecord]:
        """Return all embeddings (all backbones) for a given song."""
        with map_persistence_exceptions():
            stmt = select(_T).where(_T.c.song_id == song_id)
            result = self._session.execute(stmt)
            return [_row_to_embedding_record(r) for r in result.all()]

    def count_cold_embeddings(self, backbone_id: str) -> int:
        """Count cold-tier embeddings for a given backbone."""
        with map_persistence_exceptions():
            stmt = (
                select(func.count())
                .select_from(_T)
                .where(
                    _T.c.tier == "cold",
                    _T.c.backbone_id == backbone_id,
                )
            )
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def get_embedding_stats(self, backbone_id: str) -> dict[str, int]:
        """Return hot and cold embedding counts for a given backbone."""
        with map_persistence_exceptions():
            stmt = (
                select(_T.c.tier, func.count().label("cnt")).where(_T.c.backbone_id == backbone_id).group_by(_T.c.tier)
            )
            result = self._session.execute(stmt)
            counts: dict[str, int] = {"hot_count": 0, "cold_count": 0}
            for row in result.all():
                m = row._mapping
                tier = m["tier"]
                cnt = m["cnt"]
                if tier == "hot":
                    counts["hot_count"] = cnt
                elif tier == "cold":
                    counts["cold_count"] = cnt
            return counts

    # ── delete / truncate ───────────────────────────────────────

    def delete_all_embeddings(self) -> None:
        """Delete all rows from the ``embeddings`` table."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T))
            self._session.commit()

    def delete_embeddings_for_song(self, song_id: int) -> None:
        """Delete all embeddings for a given song."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T).where(_T.c.song_id == song_id)
                self._session.execute(stmt)
            self._session.commit()

    def truncate_embeddings(self) -> None:
        """Truncate the ``embeddings`` table (full reset).

        Uses ``TRUNCATE TABLE`` for performance on full resets — distinct
        from ``delete_all_embeddings`` only in semantic intent.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(text("TRUNCATE TABLE embeddings"))
            self._session.commit()
