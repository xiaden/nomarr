"""MlOutputStream ORM model — canonical ML output stream records.

``ml_output_streams`` stores canonical ``{output_id, values}`` output stream
rows for each song. ``ml_model_outputs`` remains a metadata table used only to
enrich reads (resolving an ``output_id`` to head/label metadata); it is not a
stream store.
"""

from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class MlOutputStream(Base):
    """Canonical ML output stream for one song/output pair."""

    __tablename__ = "ml_output_streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    output_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    output_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    values: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)
