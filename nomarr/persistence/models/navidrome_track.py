"""NavidromeTrack ORM model — Navidrome track metadata."""

from sqlalchemy import BigInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class NavidromeTrack(Base):
    """Navidrome track metadata, keyed by Navidrome ID."""

    __tablename__ = "navidrome_tracks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    artist: Mapped[str] = mapped_column(Text, nullable=False)
    album: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
