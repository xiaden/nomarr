"""NavidromePlay ORM model — records of Navidrome play events."""

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class NavidromePlay(Base):
    """Records a Navidrome play event for a track."""

    __tablename__ = "navidrome_plays"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    navidrome_track_id: Mapped[str] = mapped_column(
        ForeignKey("navidrome_tracks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    played_at: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
