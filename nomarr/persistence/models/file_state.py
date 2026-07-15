"""FileState ORM model — lookup table for file processing states."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class FileState(Base):
    """Lookup table for file processing states (e.g. 'pending', 'tagged', 'curated')."""

    __tablename__ = "file_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
