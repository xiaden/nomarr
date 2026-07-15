"""MlEmbeddingStream ORM model — tracks embedding computation progress."""

from sqlalchemy import BigInteger, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class MlEmbeddingStream(Base):
    """Tracks embedding computation progress per file/backbone pair."""

    __tablename__ = "ml_embedding_streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    backbone_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    patches_emb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)
