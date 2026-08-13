"""SongTag ORM model — junction table linking songs to tags."""

from sqlalchemy import BigInteger, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class SongTag(Base):
    """Junction table: assigns a tag to a song with confidence and source."""

    __tablename__ = "song_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default=text("1.0"))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("song_id", "tag_id", name="uq_song_tags_song_tag"),)
