"""MlModelOutput ORM model — stores ML model output data per file."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class MlModelOutput(Base):
    """Stores ML model output data (JSONB) for a file/model pair."""

    __tablename__ = "ml_model_outputs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    output_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger)

    # Extended fields from the ml_model_outputs table
    output_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fully_labeled: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
