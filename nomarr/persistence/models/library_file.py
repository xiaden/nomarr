"""LibraryFile ORM model."""

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class LibraryFile(Base):
    """Represents a single audio file within a library."""

    __tablename__ = "library_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger)
    modified_time: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    chromaprint: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    needs_tagging: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_valid: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    tagged: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    calibration_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    write_claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    last_tagged_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    scanned_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("library_id", "path", name="uq_library_files_library_path"),
        UniqueConstraint("library_id", "normalized_path", name="uq_library_files_library_norm_path"),
        Index("ix_lf_needs_tagging_valid", "needs_tagging", "is_valid"),
        Index("ix_lf_library_tagged", "library_id", "tagged"),
    )
