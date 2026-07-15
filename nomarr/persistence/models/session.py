"""Session ORM model — user session storage with expiry."""

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class Session(Base):
    """User session storage with expiry timestamp."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
