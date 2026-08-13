"""SongStateAssignment ORM model — junction table linking songs to states."""

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class SongStateAssignment(Base):
    """Junction table: assigns a processing state to a song."""

    __tablename__ = "song_state_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("song_states.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("song_id", "state_id", name="uq_song_state_assign_song_state"),)
