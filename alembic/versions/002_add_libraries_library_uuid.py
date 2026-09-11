"""Add immutable ``libraries.library_uuid`` application identity.

Revision ID: 002_libraries_library_uuid
Revises: baseline_20260830
Create Date: 2026-09-10 00:00:00.000000

ADR-049 introduces ``libraries.library_uuid`` as the immutable, NOT NULL,
UNIQUE Nomarr-minted library application identity carried by the SongLocator.
Nomarr is pre-production: this hard-cut mutation adds the column, backfills
every existing library with a freshly minted UUID, then enforces NOT NULL and
UNIQUE. No compatibility/dual path is created. Integer ``libraries.id`` remains
the persistence PK/FK/index anchor.

``alembic upgrade head`` always applies the baseline before this revision. The
amended ``001_current_schema_baseline`` already declares ``library_uuid`` for
freshly initialized databases, so ``upgrade`` inspects the live schema and is a
no-op when the column already exists; only a database created before the
amendment takes the add/backfill/enforce path.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_libraries_library_uuid"
down_revision: str | None = "baseline_20260830"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _library_uuid_column_exists() -> bool:
    """True when ``libraries.library_uuid`` is already present in the live schema."""
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("libraries")}
    return "library_uuid" in columns


def upgrade() -> None:
    # Fresh databases initialize from the amended baseline, which already
    # declares the NOT NULL UNIQUE column; nothing to backfill or enforce.
    if _library_uuid_column_exists():
        return

    # 1. Add the column nullable so existing rows can be backfilled first.
    op.add_column("libraries", sa.Column("library_uuid", sa.String(length=36), nullable=True))

    # 2. Mint a UUID for every existing library row. UUIDs are generated in
    #    Python (not ``gen_random_uuid()``) so the migration does not depend on
    #    a PostgreSQL extension being installed.
    bind = op.get_bind()
    existing_ids = bind.execute(sa.text("SELECT id FROM libraries")).fetchall()
    for (library_id,) in existing_ids:
        bind.execute(
            sa.text("UPDATE libraries SET library_uuid = :library_uuid WHERE id = :library_id"),
            {"library_uuid": str(uuid.uuid4()), "library_id": library_id},
        )

    # 3. Enforce the identity contract only after every row carries a value.
    op.alter_column("libraries", "library_uuid", existing_type=sa.String(length=36), nullable=False)
    op.create_unique_constraint("uq_libraries_library_uuid", "libraries", ["library_uuid"])


def downgrade() -> None:
    if not _library_uuid_column_exists():
        return
    inspector = sa.inspect(op.get_bind())
    constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("libraries")}
    if "uq_libraries_library_uuid" in constraints:
        op.drop_constraint("uq_libraries_library_uuid", "libraries", type_="unique")
    op.drop_column("libraries", "library_uuid")
