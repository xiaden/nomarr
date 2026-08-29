"""LibraryFolder ORM model."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class LibraryFolder(Base):
    """Represents a folder within a library."""

    __tablename__ = "library_folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mtime: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scanned_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
