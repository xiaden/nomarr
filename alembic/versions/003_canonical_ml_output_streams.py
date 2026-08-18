"""Canonical ML output stream schema.

Migrates ``ml_output_streams`` from the obsolete ``{model_id, status}`` shape to
canonical output identifiers and values, removes the obsolete model/status
foreign-key contract, and adds the ``(song_id, backbone_id)`` uniqueness needed
by embedding streams. The downgrade reverses only these two tables' changes and
does not alter unrelated tables.

Revision ID: 003_canonical_ml_output_streams
Revises: 002_drop_navidrome_tables
Create Date: 2026-08-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_canonical_ml_output_streams"
down_revision: str | None = "002_drop_navidrome_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── ml_output_streams: canonical output identifiers/values ──
    # Drop the obsolete model foreign-key contract and the status column, then
    # add canonical output identifiers/values.  Tables are empty under the
    # AR-SDR-2 hard-cut doctrine, so NOT NULL additions need no server default.
    op.drop_constraint("ml_output_streams_model_id_fkey", "ml_output_streams", type_="foreignkey")
    op.drop_index("ix_ml_output_streams_model_id", table_name="ml_output_streams")
    op.drop_column("ml_output_streams", "model_id")
    op.drop_column("ml_output_streams", "status")
    op.add_column("ml_output_streams", sa.Column("output_id", sa.String(length=255), nullable=False))
    op.add_column("ml_output_streams", sa.Column("output_index", sa.Integer(), nullable=True))
    op.add_column("ml_output_streams", sa.Column("values", postgresql.JSONB(), nullable=False))
    op.create_index("ix_ml_output_streams_output_id", "ml_output_streams", ["output_id"])

    # ── ml_embedding_streams: (song_id, backbone_id) uniqueness ──
    op.create_unique_constraint(
        "uq_ml_embedding_streams_song_backbone",
        "ml_embedding_streams",
        ["song_id", "backbone_id"],
    )


def downgrade() -> None:
    # ── ml_embedding_streams ──
    op.drop_constraint("uq_ml_embedding_streams_song_backbone", "ml_embedding_streams", type_="unique")

    # ── ml_output_streams ──
    op.drop_index("ix_ml_output_streams_output_id", table_name="ml_output_streams")
    op.drop_column("ml_output_streams", "values")
    op.drop_column("ml_output_streams", "output_index")
    op.drop_column("ml_output_streams", "output_id")
    op.add_column("ml_output_streams", sa.Column("status", sa.String(length=50), nullable=False))
    op.add_column("ml_output_streams", sa.Column("model_id", sa.String(length=255), nullable=False))
    op.create_foreign_key(
        "ml_output_streams_model_id_fkey",
        "ml_output_streams",
        "ml_models",
        ["model_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_ml_output_streams_model_id", "ml_output_streams", ["model_id"])
