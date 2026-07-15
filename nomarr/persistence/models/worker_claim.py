"""WorkerClaim ORM model — file processing claims by workers."""

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class WorkerClaim(Base):
    """Tracks file processing claims by workers."""

    __tablename__ = "worker_claims"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    claimed_at: Mapped[int] = mapped_column(BigInteger, index=True)
