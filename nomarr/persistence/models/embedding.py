"""Embedding ORM model — single-table design for all vector embeddings."""

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Embedding(Base):
    """Single-table design for all vector embeddings.

    Uses HalfVector (halfvec) for 50% storage savings with identical recall.
    Partial HNSW index on cold-tier embeddings only — hot-tier embeddings
    are never ANN-searched.
    """

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    backbone_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    embed_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model_suite_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    num_segments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segmentation_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    embedding = mapped_column(HALFVEC(1280))
    genres: Mapped[list[str] | None] = mapped_column(PG_ARRAY(String), nullable=True)
    tier: Mapped[str] = mapped_column(String(10), nullable=False, default="hot", server_default=text("'hot'"))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("file_id", "backbone_id", name="uq_embeddings_file_backbone"),
        Index("ix_embeddings_backbone_tier", "backbone_id", "tier"),
        Index(
            "ix_embeddings_cold_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": "16", "ef_construction": "200"},
            postgresql_ops={"embedding": "halfvec_cosine_ops"},
            postgresql_where=text("tier = 'cold'"),
        ),
    )
