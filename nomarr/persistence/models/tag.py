"""Tag ORM model."""

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Tag(Base):
    """Represents a tag in the unified tag schema (name, value, namespace)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(50), nullable=False)
    parent_tag_id: Mapped[int | None] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    # Legacy column: kept for schema stability, never populated by any code
    # path. ML scores live on tag_model_output (see DD-song-domain-repair Q5).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Legacy column: kept for schema stability, never populated by any code
    # path. ML scores live on tag_model_output (see DD-song-domain-repair Q5).
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("name", "value", "namespace", name="uq_tags_name_value_ns"),)
