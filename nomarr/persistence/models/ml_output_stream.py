"""MlOutputStream ORM model — tracks ML output streaming status per song."""

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class MlOutputStream(Base):
    """Tracks ML output streaming status for a song/model pair."""

    __tablename__ = "ml_output_streams"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)
