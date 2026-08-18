"""Library ORM model."""

from sqlalchemy import BigInteger, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Library(Base):
    """Represents a music library directory."""

    __tablename__ = "libraries"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    library_type: Mapped[str] = mapped_column(String(50), nullable=False)
    auto_tag: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    auto_curate: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    watch_mode: Mapped[str] = mapped_column(String(20), default="off", server_default=text("'off'"))
    file_write_mode: Mapped[str] = mapped_column(String(20), default="full", server_default=text("'full'"))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)
