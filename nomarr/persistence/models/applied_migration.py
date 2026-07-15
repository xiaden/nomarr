"""AppliedMigration ORM model — tracks applied database migrations."""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class AppliedMigration(Base):
    """Tracks applied database migrations with status and timing."""

    __tablename__ = "applied_migrations"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    migration_version: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[int] = mapped_column(BigInteger)
    applied_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
