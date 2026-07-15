"""Meta ORM model — key-value metadata storage."""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Meta(Base):
    """Key-value metadata storage (e.g. schema version, feature flags)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
