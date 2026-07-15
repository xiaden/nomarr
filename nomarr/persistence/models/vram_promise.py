"""VramPromise ORM model — GPU VRAM promise tracking for workers."""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class VramPromise(Base):
    """GPU VRAM promise tracking for ML workers."""

    __tablename__ = "vram_promises"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    model_path: Mapped[str] = mapped_column(Text, nullable=False)
    promised_mb: Mapped[float] = mapped_column(Float, nullable=False)
    total_mb: Mapped[float] = mapped_column(Float, nullable=False)
    used_mb: Mapped[float] = mapped_column(Float, nullable=False)
