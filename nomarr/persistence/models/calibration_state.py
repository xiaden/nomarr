"""CalibrationState ORM model — stores calibration state per ML model."""

from sqlalchemy import BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class CalibrationState(Base):
    """Stores current calibration state for an ML model."""

    __tablename__ = "calibration_states"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ml_models.id", ondelete="CASCADE"), nullable=False, index=True)
    state_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, index=True)
