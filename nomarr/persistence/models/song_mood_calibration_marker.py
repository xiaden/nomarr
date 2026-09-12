"""Private current mood-publication marker model."""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class SongMoodCalibrationMarker(Base):
    """One current calibration marker per persistence-private song row."""

    __tablename__ = "song_mood_calibration_markers"

    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    calibration_version: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (CheckConstraint("calibration_version ~ '^[0-9a-f]{32}$'"),)
