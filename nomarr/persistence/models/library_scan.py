"""LibraryScan ORM model — tracks library scan operations."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class LibraryScan(Base):
    """Records a library scan operation with status and progress counters."""

    __tablename__ = "library_scans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    scan_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger)
    finished_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    files_found: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    files_processed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
