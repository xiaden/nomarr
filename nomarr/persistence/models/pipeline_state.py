"""PipelineState ORM model — per-library pipeline state storage."""

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class PipelineState(Base):
    """Stores per-library pipeline state as JSONB key-value pairs."""

    __tablename__ = "pipeline_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False, index=True)
    state_key: Mapped[str] = mapped_column(String(100), nullable=False)
    state_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("library_id", "state_key", name="uq_pipeline_states_lib_key"),)
