"""Add ML model fields.

Revision ID: 002_add_ml_model_fields
Revises: 001_initial
Create Date: 2026-07-15 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_add_ml_model_fields"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ml_models: add 11 new columns
    op.add_column("ml_models", sa.Column("path", sa.String(length=512), nullable=True))
    op.add_column("ml_models", sa.Column("backbone", sa.String(length=100), nullable=True))
    op.add_column("ml_models", sa.Column("head_type", sa.String(length=100), nullable=True))
    op.add_column("ml_models", sa.Column("model_stem", sa.String(length=255), nullable=True))
    op.add_column("ml_models", sa.Column("output_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("ml_models", sa.Column("fully_configured", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("ml_models", sa.Column("is_known", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column(
        "ml_models", sa.Column("source", sa.String(length=100), nullable=False, server_default=sa.text("'discovered'"))
    )
    op.add_column("ml_models", sa.Column("head_release_date", sa.String(length=50), nullable=True))
    op.add_column("ml_models", sa.Column("embedder_release_date", sa.String(length=50), nullable=True))
    op.add_column("ml_models", sa.Column("registered_at", sa.BigInteger(), nullable=True))

    # ml_models: create indexes and unique constraint
    op.create_index("ix_ml_models_path", "ml_models", ["path"])
    op.create_index("ix_ml_models_backbone", "ml_models", ["backbone"])
    op.create_unique_constraint("uq_ml_models_path", "ml_models", ["path"])

    # ml_model_outputs: add 3 new columns
    op.add_column("ml_model_outputs", sa.Column("output_index", sa.Integer(), nullable=True))
    op.add_column("ml_model_outputs", sa.Column("label", sa.String(length=255), nullable=True))
    op.add_column(
        "ml_model_outputs", sa.Column("fully_labeled", sa.Integer(), nullable=False, server_default=sa.text("0"))
    )


def downgrade() -> None:
    # ml_model_outputs: drop columns (reverse order)
    op.drop_column("ml_model_outputs", "fully_labeled")
    op.drop_column("ml_model_outputs", "label")
    op.drop_column("ml_model_outputs", "output_index")

    # ml_models: drop indexes and unique constraint
    op.drop_constraint("uq_ml_models_path", "ml_models", type_="unique")
    op.drop_index("ix_ml_models_backbone", table_name="ml_models")
    op.drop_index("ix_ml_models_path", table_name="ml_models")

    # ml_models: drop columns (reverse order)
    op.drop_column("ml_models", "registered_at")
    op.drop_column("ml_models", "embedder_release_date")
    op.drop_column("ml_models", "head_release_date")
    op.drop_column("ml_models", "source")
    op.drop_column("ml_models", "is_known")
    op.drop_column("ml_models", "fully_configured")
    op.drop_column("ml_models", "output_count")
    op.drop_column("ml_models", "model_stem")
    op.drop_column("ml_models", "head_type")
    op.drop_column("ml_models", "backbone")
    op.drop_column("ml_models", "path")
