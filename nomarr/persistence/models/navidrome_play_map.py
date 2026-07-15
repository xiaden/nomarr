"""NavidromePlayMap ORM model — junction mapping plays to library files."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class NavidromePlayMap(Base):
    """Junction table: maps Navidrome plays to library files (composite PK)."""

    __tablename__ = "navidrome_play_maps"

    play_id: Mapped[int] = mapped_column(
        ForeignKey("navidrome_plays.id", ondelete="CASCADE"),
        primary_key=True,
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[int] = mapped_column(BigInteger)
