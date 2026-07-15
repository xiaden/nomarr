"""Health ORM model — worker/component health status."""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Health(Base):
    """Worker/component health status with last-seen timestamp."""

    __tablename__ = "worker_health"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    last_seen: Mapped[int] = mapped_column(BigInteger)
