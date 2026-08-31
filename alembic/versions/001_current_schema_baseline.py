"""Current PostgreSQL schema baseline.

This is the complete schema for fresh Nomarr installations. The pre-stability
revision history was intentionally collapsed; databases created from prior
revisions are unsupported and must be recreated.

Revision ID: baseline_20260830
Revises:
Create Date: 2026-08-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "baseline_20260830"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable required PostgreSQL extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # libraries
    op.create_table(
        "libraries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("library_type", sa.String(length=50), nullable=False),
        sa.Column("auto_tag", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("auto_curate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("watch_mode", sa.String(length=20), nullable=False, server_default=sa.text("'off'")),
        sa.Column("file_write_mode", sa.String(length=20), nullable=False, server_default=sa.text("'full'")),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_libraries_name"),
    )

    # library_folders
    op.create_table(
        "library_folders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("mtime", sa.BigInteger(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("last_scanned_at", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["library_folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_library_folders_library_id", "library_folders", ["library_id"])
    op.create_index("ix_library_folders_parent_id", "library_folders", ["parent_id"])

    # songs
    op.create_table(
        "songs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("modified_time", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("chromaprint", sa.String(length=255), nullable=True),
        sa.Column("needs_tagging", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_valid", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tagged", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("calibration_hash", sa.String(length=255), nullable=True),
        sa.Column("write_claimed_by", sa.String(length=255), nullable=True),
        sa.Column("last_tagged_at", sa.BigInteger(), nullable=True),
        sa.Column("scanned_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["library_folders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_id", "path", name="uq_songs_library_path"),
        sa.UniqueConstraint("library_id", "normalized_path", name="uq_songs_library_norm_path"),
    )
    op.create_index("ix_songs_library_id", "songs", ["library_id"])
    op.create_index("ix_songs_folder_id", "songs", ["folder_id"])
    op.create_index("ix_songs_chromaprint", "songs", ["chromaprint"])
    op.create_index("ix_songs_calibration_hash", "songs", ["calibration_hash"])
    op.create_index("ix_songs_write_claimed_by", "songs", ["write_claimed_by"])
    op.create_index("ix_songs_needs_tagging_valid", "songs", ["needs_tagging", "is_valid"])
    op.create_index("ix_songs_library_tagged", "songs", ["library_id", "tagged"])

    # tags
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("namespace", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", "name", "value", name="uq_tags_name_value_ns"),
    )

    # GIN trigram index for fuzzy search
    op.execute("CREATE INDEX ix_songs_normalized_path_trgm ON songs USING gin (normalized_path gin_trgm_ops)")

    # song_tags
    op.create_table(
        "song_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("song_id", "tag_id", name="uq_song_tags_song_tag"),
    )
    op.create_index("ix_song_tags_song_id", "song_tags", ["song_id"])
    op.create_index("ix_song_tags_tag_id", "song_tags", ["tag_id"])

    # song_states
    op.create_table(
        "song_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # song_state_assignments
    op.create_table(
        "song_state_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("state_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["state_id"], ["song_states.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("song_id", "state_id", name="uq_song_state_assign_song_state"),
    )
    op.create_index("ix_song_state_assignments_song_id", "song_state_assignments", ["song_id"])
    op.create_index("ix_song_state_assignments_state_id", "song_state_assignments", ["state_id"])

    # pipeline_states
    op.create_table(
        "pipeline_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("state_key", sa.String(length=100), nullable=False),
        sa.Column("state_data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_id", "state_key", name="uq_pipeline_states_lib_key"),
    )
    op.create_index("ix_pipeline_states_library_id", "pipeline_states", ["library_id"])

    # library_scans
    op.create_table(
        "library_scans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("scan_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.Column("heartbeat_at", sa.BigInteger(), nullable=True),
        sa.Column("files_found", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_library_scans_library_id", "library_scans", ["library_id"])
    op.create_index(
        "uq_library_scans_one_in_progress",
        "library_scans",
        ["library_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )

    # ml_models
    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("model_type", sa.String(length=100), nullable=False),
        sa.Column("backbone_id", sa.String(length=100), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=True),
        sa.Column("backbone", sa.String(length=100), nullable=True),
        sa.Column("head_type", sa.String(length=100), nullable=True),
        sa.Column("model_stem", sa.String(length=255), nullable=True),
        sa.Column("output_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("fully_configured", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_known", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("source", sa.String(length=100), nullable=False, server_default=sa.text("'discovered'")),
        sa.Column("head_release_date", sa.String(length=50), nullable=True),
        sa.Column("embedder_release_date", sa.String(length=50), nullable=True),
        sa.Column("registered_at", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path", name="uq_ml_models_path"),
    )
    op.create_index("ix_ml_models_path", "ml_models", ["path"])
    op.create_index("ix_ml_models_backbone", "ml_models", ["backbone"])
    op.create_index("ix_ml_models_updated_at", "ml_models", ["updated_at"])

    # ml_output_streams
    op.create_table(
        "ml_output_streams",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("output_id", sa.String(length=255), nullable=False),
        sa.Column("output_index", sa.Integer(), nullable=True),
        sa.Column("values", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ml_output_streams_song_id", "ml_output_streams", ["song_id"])
    op.create_index("ix_ml_output_streams_output_id", "ml_output_streams", ["output_id"])

    # ml_embedding_streams
    op.create_table(
        "ml_embedding_streams",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("backbone_id", sa.String(length=100), nullable=False),
        sa.Column("patches_emb", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ml_embedding_streams_song_id", "ml_embedding_streams", ["song_id"])
    op.create_index("ix_ml_embedding_streams_backbone_id", "ml_embedding_streams", ["backbone_id"])
    op.create_unique_constraint(
        "uq_ml_embedding_streams_song_backbone",
        "ml_embedding_streams",
        ["song_id", "backbone_id"],
    )

    # ml_model_outputs
    op.create_table(
        "ml_model_outputs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("output_id", sa.String(length=255), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("output_data", postgresql.JSONB(), nullable=False),
        sa.Column("output_index", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("fully_labeled", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("output_id", name="uq_ml_model_outputs_output_id"),
    )
    op.create_index("ix_ml_model_outputs_output_id", "ml_model_outputs", ["output_id"])
    op.create_index("ix_ml_model_outputs_model_id", "ml_model_outputs", ["model_id"])

    # calibration_states
    op.create_table(
        "calibration_states",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("state_data", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_states_model_id", "calibration_states", ["model_id"])
    op.create_index("ix_calibration_states_updated_at", "calibration_states", ["updated_at"])

    # calibration_history
    op.create_table(
        "calibration_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("event", sa.String(length=255), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_history_model_id", "calibration_history", ["model_id"])

    # meta
    op.create_table(
        "meta",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    # worker_health
    op.create_table(
        "worker_health",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("last_seen", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_health_worker_id", "worker_health", ["worker_id"])

    # worker_claims
    op.create_table(
        "worker_claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("claimed_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_worker_claims_key"),
    )
    op.create_index("ix_worker_claims_worker_id", "worker_claims", ["worker_id"])
    op.create_index("ix_worker_claims_claimed_at", "worker_claims", ["claimed_at"])

    # locks
    op.create_table(
        "locks",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )

    # worker_restart_policies
    op.create_table(
        "worker_restart_policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("component_id", sa.String(length=255), nullable=False),
        sa.Column("policy_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("component_id", name="uq_worker_restart_policies_component_id"),
    )

    # applied_migrations
    op.create_table(
        "applied_migrations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("migration_version", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("applied_at", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )

    # vram_promises
    op.create_table(
        "vram_promises",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("worker_id", sa.String(length=255), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("model_path", sa.Text(), nullable=False),
        sa.Column("promised_mb", sa.Float(), nullable=False),
        sa.Column("total_mb", sa.Float(), nullable=False),
        sa.Column("used_mb", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vram_promises_worker_id", "vram_promises", ["worker_id"])

    # embeddings (most critical - with partial HNSW index)
    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("song_id", sa.Integer(), nullable=False),
        sa.Column("backbone_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column("embed_dim", sa.Integer(), nullable=False),
        sa.Column("model_suite_hash", sa.String(length=255), nullable=False),
        sa.Column("num_segments", sa.Integer(), nullable=True),
        sa.Column("segmentation_hash", sa.String(length=255), nullable=True),
        sa.Column("embedding", HALFVEC(1280), nullable=False),
        sa.Column("genres", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tier", sa.String(length=10), nullable=False, server_default="hot"),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("song_id", "backbone_id", name="uq_embeddings_song_backbone"),
    )
    op.create_index("ix_embeddings_song_id", "embeddings", ["song_id"])
    op.create_index("ix_embeddings_backbone_id", "embeddings", ["backbone_id"])
    op.create_index("ix_embeddings_model_id", "embeddings", ["model_id"])
    op.create_index("ix_embeddings_backbone_tier", "embeddings", ["backbone_id", "tier"])

    # Set maintenance_work_mem for HNSW index build (prevents disk fallback)
    op.execute("SET maintenance_work_mem = '2GB'")

    # Create partial HNSW index on cold-tier embeddings only
    op.create_index(
        "ix_embeddings_cold_hnsw",
        "embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 200},
        postgresql_ops={"embedding": "halfvec_cosine_ops"},
        postgresql_where=sa.text("tier = 'cold'"),
    )

    # Reset maintenance_work_mem to default
    op.execute("RESET maintenance_work_mem")


def downgrade() -> None:
    """Drop the complete baseline schema."""
    op.drop_index("ix_vram_promises_worker_id", table_name="vram_promises")
    op.drop_table("vram_promises")
    op.drop_table("applied_migrations")
    op.drop_constraint(
        "uq_worker_restart_policies_component_id",
        "worker_restart_policies",
        type_="unique",
    )
    op.drop_table("worker_restart_policies")
    op.drop_table("locks")
    op.drop_index("ix_worker_claims_claimed_at", table_name="worker_claims")
    op.drop_index("ix_worker_claims_worker_id", table_name="worker_claims")
    op.drop_table("worker_claims")
    op.drop_index("ix_worker_health_worker_id", table_name="worker_health")
    op.drop_table("worker_health")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("meta")
    op.drop_index("ix_calibration_history_model_id", table_name="calibration_history")
    op.drop_table("calibration_history")
    op.drop_index("ix_calibration_states_updated_at", table_name="calibration_states")
    op.drop_index("ix_calibration_states_model_id", table_name="calibration_states")
    op.drop_table("calibration_states")
    op.drop_index("ix_ml_model_outputs_model_id", table_name="ml_model_outputs")
    op.drop_index("ix_ml_model_outputs_output_id", table_name="ml_model_outputs")
    op.drop_table("ml_model_outputs")
    op.drop_constraint(
        "uq_ml_embedding_streams_song_backbone",
        "ml_embedding_streams",
        type_="unique",
    )
    op.drop_index("ix_ml_embedding_streams_backbone_id", table_name="ml_embedding_streams")
    op.drop_index("ix_ml_embedding_streams_song_id", table_name="ml_embedding_streams")
    op.drop_table("ml_embedding_streams")
    op.drop_index("ix_ml_output_streams_output_id", table_name="ml_output_streams")
    op.drop_index("ix_ml_output_streams_song_id", table_name="ml_output_streams")
    op.drop_table("ml_output_streams")
    op.drop_index("ix_ml_models_updated_at", table_name="ml_models")
    op.drop_index("ix_ml_models_backbone", table_name="ml_models")
    op.drop_index("ix_ml_models_path", table_name="ml_models")
    op.drop_table("ml_models")
    op.drop_index("uq_library_scans_one_in_progress", table_name="library_scans")
    op.drop_index("ix_library_scans_library_id", table_name="library_scans")
    op.drop_table("library_scans")
    op.drop_index("ix_pipeline_states_library_id", table_name="pipeline_states")
    op.drop_table("pipeline_states")
    op.drop_index("ix_song_state_assignments_state_id", table_name="song_state_assignments")
    op.drop_index("ix_song_state_assignments_song_id", table_name="song_state_assignments")
    op.drop_table("song_state_assignments")
    op.drop_table("song_states")
    op.drop_index("ix_song_tags_tag_id", table_name="song_tags")
    op.drop_index("ix_song_tags_song_id", table_name="song_tags")
    op.drop_table("song_tags")
    op.drop_table("tags")

    # embeddings must be dropped BEFORE songs (FK: embeddings.song_id → songs.id)
    op.drop_index("ix_embeddings_cold_hnsw", table_name="embeddings")
    op.drop_index("ix_embeddings_backbone_tier", table_name="embeddings")
    op.drop_index("ix_embeddings_model_id", table_name="embeddings")
    op.drop_index("ix_embeddings_backbone_id", table_name="embeddings")
    op.drop_index("ix_embeddings_song_id", table_name="embeddings")
    op.drop_table("embeddings")

    op.drop_index("ix_songs_library_tagged", table_name="songs")
    op.drop_index("ix_songs_needs_tagging_valid", table_name="songs")
    op.drop_index("ix_songs_write_claimed_by", table_name="songs")
    op.drop_index("ix_songs_calibration_hash", table_name="songs")
    op.drop_index("ix_songs_chromaprint", table_name="songs")
    op.drop_index("ix_songs_folder_id", table_name="songs")
    op.drop_index("ix_songs_library_id", table_name="songs")
    op.execute("DROP INDEX IF EXISTS ix_songs_normalized_path_trgm")
    op.drop_table("songs")
    op.drop_index("ix_library_folders_parent_id", table_name="library_folders")
    op.drop_index("ix_library_folders_library_id", table_name="library_folders")
    op.drop_table("library_folders")
    op.drop_table("libraries")

    # Disable PostgreSQL extensions
    op.execute("DROP EXTENSION IF EXISTS vector CASCADE")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm CASCADE")
