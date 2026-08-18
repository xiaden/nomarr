"""Drop Navidrome persistence tables.

Nomarr must never persist Navidrome data locally — play data flows through
the plugin/request boundary only. This migration removes the four
Navidrome-local tables created in 001_initial.

Revision ID: 002_drop_navidrome_tables
Revises: 001_initial
Create Date: 2026-08-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_drop_navidrome_tables"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop child/junction tables first (FK-safe order), mirroring the reverse
    # of 001_initial's create order. Indexes are dropped before each table.
    op.drop_index("ix_navidrome_play_maps_song_id", table_name="navidrome_play_maps")
    op.drop_table("navidrome_play_maps")

    op.drop_index("ix_navidrome_plays_played_at", table_name="navidrome_plays")
    op.drop_index("ix_navidrome_plays_navidrome_track_id", table_name="navidrome_plays")
    op.drop_table("navidrome_plays")

    op.drop_index("ix_navidrome_track_maps_song_id", table_name="navidrome_track_maps")
    op.drop_table("navidrome_track_maps")

    op.drop_index("ix_navidrome_tracks_file_path", table_name="navidrome_tracks")
    op.drop_table("navidrome_tracks")


def downgrade() -> None:
    # Recreate the tables in FK-safe order (mirrors 001_initial's create).
    op.create_table(
        "navidrome_tracks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("artist", sa.Text(), nullable=False),
        sa.Column("album", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navidrome_tracks_file_path", "navidrome_tracks", ["file_path"])

    op.create_table(
        "navidrome_track_maps",
        sa.Column("navidrome_track_id", sa.Text(), nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["navidrome_track_id"], ["navidrome_tracks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("navidrome_track_id", "song_id"),
    )
    op.create_index("ix_navidrome_track_maps_song_id", "navidrome_track_maps", ["song_id"])

    op.create_table(
        "navidrome_plays",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("navidrome_track_id", sa.Text(), nullable=False),
        sa.Column("played_at", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["navidrome_track_id"], ["navidrome_tracks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navidrome_plays_navidrome_track_id", "navidrome_plays", ["navidrome_track_id"])
    op.create_index("ix_navidrome_plays_played_at", "navidrome_plays", ["played_at"])

    op.create_table(
        "navidrome_play_maps",
        sa.Column("play_id", sa.Integer(), nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["play_id"], ["navidrome_plays.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("play_id", "song_id"),
    )
    op.create_index("ix_navidrome_play_maps_song_id", "navidrome_play_maps", ["song_id"])
