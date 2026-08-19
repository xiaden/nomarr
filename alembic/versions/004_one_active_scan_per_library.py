"""Enforce one active library scan per library.

Revision ID: 004_one_active_scan_per_library
Revises: 003_canonical_ml_output_streams
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004_one_active_scan_per_library"
down_revision: str | None = "003_canonical_ml_output_streams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_library_scans_one_in_progress",
        "library_scans",
        ["library_id"],
        unique=True,
        postgresql_where="status = 'in_progress'",
    )


def downgrade() -> None:
    op.drop_index("uq_library_scans_one_in_progress", table_name="library_scans")
