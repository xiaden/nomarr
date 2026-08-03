"""FileTag ORM model — junction table linking files to tags."""

from sqlalchemy import BigInteger, Float, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class SongTag(Base):
    """Junction table: assigns a tag to a library file with confidence and source."""

    __tablename__ = "file_tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default=text("1.0"))
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("file_id", "tag_id", name="uq_file_tags_file_tag"),)
