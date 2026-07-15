"""NavidromeTrackMap ORM model — junction mapping Navidrome tracks to library files."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class NavidromeTrackMap(Base):
    """Junction table: maps Navidrome tracks to library files (composite PK)."""

    __tablename__ = "navidrome_track_maps"

    navidrome_track_id: Mapped[str] = mapped_column(
        ForeignKey("navidrome_tracks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[int] = mapped_column(BigInteger)
