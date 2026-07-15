"""WorkerRestartPolicy ORM model — restart policy configuration per component."""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nomarr.persistence.models.base import Base


class WorkerRestartPolicy(Base):
    """Restart policy configuration for a component."""

    __tablename__ = "worker_restart_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    component_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    policy_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
