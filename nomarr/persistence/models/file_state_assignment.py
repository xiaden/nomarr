"""FileStateAssignment ORM model — junction table linking files to states."""

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class FileStateAssignment(Base):
    """Junction table: assigns a processing state to a library file."""

    __tablename__ = "file_state_assignments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="CASCADE"), nullable=False, index=True)
    state_id: Mapped[int] = mapped_column(ForeignKey("file_states.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("file_id", "state_id", name="uq_file_state_assign_file_state"),)
