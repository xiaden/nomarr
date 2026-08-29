"""Add metadata columns used by incremental folder scanning.

Revision ID: 006_add_folder_cache_metadata
Revises: 005_stable_ml_output_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006_add_folder_cache_metadata"
down_revision: str | None = "005_stable_ml_output_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("library_folders", sa.Column("mtime", sa.BigInteger(), nullable=True))
    op.add_column("library_folders", sa.Column("file_count", sa.Integer(), nullable=True))
    op.add_column("library_folders", sa.Column("last_scanned_at", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("library_folders", "last_scanned_at")
    op.drop_column("library_folders", "file_count")
    op.drop_column("library_folders", "mtime")
