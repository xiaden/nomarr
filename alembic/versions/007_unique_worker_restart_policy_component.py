"""Enforce one restart policy row per worker component.

Revision ID: 007_unique_worker_restart_policy_component
Revises: 006_add_folder_cache_metadata
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007_unique_worker_restart_policy_component"
down_revision: str | None = "006_add_folder_cache_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the newest row when repairing databases that contain duplicates.
    # The id is monotonic and therefore represents the latest write.
    op.execute(
        """
        DELETE FROM worker_restart_policies AS duplicate
        USING worker_restart_policies AS retained
        WHERE duplicate.component_id = retained.component_id
          AND duplicate.id < retained.id
        """
    )
    op.drop_index("ix_worker_restart_policies_component_id", table_name="worker_restart_policies")
    op.create_unique_constraint(
        "uq_worker_restart_policies_component_id",
        "worker_restart_policies",
        ["component_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_worker_restart_policies_component_id",
        "worker_restart_policies",
        type_="unique",
    )
    op.create_index("ix_worker_restart_policies_component_id", "worker_restart_policies", ["component_id"])
