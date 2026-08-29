"""Add stable output identities to registered ML outputs and drop the fake song FK.

``ml_model_outputs`` is model-scoped metadata (one row per output vertex of a
registered model), not per-song data.  Its ``song_id`` FK to ``songs.id`` was
never backed by a real song — production call sites passed ``song_id=0`` (no
songs.id=0 exists), which violated FK integrity.  ADR-040 requires FK
integrity; ADR-041 keeps persistence PKs internal and natural identity
separate.  This revision gives the table its stable natural identity
``output_id`` (sha256 ``_output_key`` from the model registry) and removes the
fake song FK entirely.  No sentinel song is invented.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_stable_ml_output_identity"
down_revision: str | None = "004_one_active_scan_per_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ml_model_outputs", sa.Column("output_id", sa.String(length=255), nullable=True))
    # The hard-cut schema has no production rows before this migration.
    op.execute("UPDATE ml_model_outputs SET output_id = md5('legacy:' || id::text) WHERE output_id IS NULL")
    op.alter_column("ml_model_outputs", "output_id", nullable=False)
    op.create_unique_constraint("uq_ml_model_outputs_output_id", "ml_model_outputs", ["output_id"])
    op.create_index("ix_ml_model_outputs_output_id", "ml_model_outputs", ["output_id"])
    # Model outputs are model-scoped metadata — drop the fake song FK and column.
    op.drop_constraint("ml_model_outputs_song_id_fkey", "ml_model_outputs", type_="foreignkey")
    op.drop_index("ix_ml_model_outputs_song_id", table_name="ml_model_outputs")
    op.drop_column("ml_model_outputs", "song_id")


def downgrade() -> None:
    op.drop_index("ix_ml_model_outputs_output_id", table_name="ml_model_outputs")
    op.drop_constraint("uq_ml_model_outputs_output_id", "ml_model_outputs", type_="unique")
    op.drop_column("ml_model_outputs", "output_id")
    # Re-add the song FK.  Column is nullable because there is no legitimate
    # value to backfill (the old writes used the non-existent song_id=0).
    op.add_column("ml_model_outputs", sa.Column("song_id", sa.Integer(), nullable=True))
    op.create_index("ix_ml_model_outputs_song_id", "ml_model_outputs", ["song_id"])
    op.create_foreign_key(
        "ml_model_outputs_song_id_fkey",
        "ml_model_outputs",
        "songs",
        ["song_id"],
        ["id"],
        ondelete="CASCADE",
    )
