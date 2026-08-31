"""Tag ORM model — reusable tag identity only.

``tags`` carries exactly the identity tuple ``(id, namespace, name, value)``
with uniqueness over the complete ``(namespace, name, value)``. Relationship
metadata (confidence, source, assignment timestamps) is owned by the
``song_tags`` edge, not the ``tags`` row.
"""

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Tag(Base):
    """Represents a reusable tag identity (id, namespace, name, value)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    namespace: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)

    __table_args__ = (UniqueConstraint("namespace", "name", "value", name="uq_tags_name_value_ns"),)
