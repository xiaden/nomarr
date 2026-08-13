"""NavidromeTrackMap ORM model — junction mapping Navidrome tracks to songs."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class NavidromeTrackMap(Base):
    """Junction table: maps Navidrome tracks to songs (composite PK)."""

    __tablename__ = "navidrome_track_maps"

    navidrome_track_id: Mapped[str] = mapped_column(
        ForeignKey("navidrome_tracks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    song_id: Mapped[int] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[int] = mapped_column(BigInteger)
