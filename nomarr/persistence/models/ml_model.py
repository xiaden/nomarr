"""MlModel ORM model — ML model registry with natural key PK."""

from sqlalchemy import BigInteger, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class MlModel(Base):
    """ML model registry. Uses model name as natural primary key."""

    __tablename__ = "ml_models"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    model_type: Mapped[str] = mapped_column(String(100), nullable=False)
    backbone_id: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger, index=True)

    # Extended fields from the ml_models table
    path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    backbone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    head_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_stem: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    fully_configured: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_known: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    source: Mapped[str] = mapped_column(String(100), default="discovered", server_default=text("'discovered'"))
    head_release_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    embedder_release_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    registered_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_ml_models_path", "path"),
        Index("ix_ml_models_backbone", "backbone"),
        UniqueConstraint("path", name="uq_ml_models_path"),
    )
