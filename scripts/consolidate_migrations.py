"""Consolidate all historical migrations into a single baseline.

Nomarr uses a baseline + delta migration pattern:
- ensure_schema() is a frozen baseline (not edited per-migration)
- Migrations are the ONLY place for schema changes
- This script consolidates: captures current DB state as the new baseline,
  deletes all migration files, and resets the schema version

Alpha-only script. Since no external users exist, this:
1. Deletes all existing migration files
2. Creates a single V001_baseline.py migration (fresh numbering)
3. Prints AQL commands to reset an existing database's schema version

After running this script:
- ensure_schema() should be manually updated to reflect the cumulative
  schema state (all collections, indexes, graphs from the deleted migrations)
- Fresh databases work automatically (updated ensure_schema + V001 baseline)
- Existing databases need the printed AQL commands run against ArangoDB
- Future migrations start at V002

Usage:
    python scripts/consolidate_migrations.py [--execute-db-reset]

    --execute-db-reset  Also reset the local dev database (requires running ArangoDB)
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "nomarr" / "migrations"

# Files to delete (all historical migrations)
MIGRATION_FILES_TO_DELETE = [
    "V004_add_segment_scores_stats.py",
    "V005_add_vectors_track_collections.py",
    "V006_add_applied_migrations.py",
    "V007_split_vectors_hot_cold.py",
    "V008_normalize_cold_vectors.py",
    "V009_rename_essentia_tag_keys.py",
    "V010_add_vram_promises.py",
    "V011_drop_vram_promises_ttl_index.py",
    "V012_drop_gpu_warmup_claims.py",
    "V013_rename_song_tag_edges_collection.py",
    "V014_add_ml_model_graph.py",
    "V015_add_navidrome_song_map.py",
    "V016_add_file_state_edges.py",
    "V017_remove_dead_state_fields.py",
    "V018_split_vectors_per_library.py",
    "V019_add_vector_promotion_locks.py",
    "V019_navidrome_graph_model.py",
]

BASELINE_MIGRATION = '''\
"""V001: Consolidated baseline schema verification.

Replaces V004-V019 historical migrations. All DDL (collections, indexes, graphs)
is handled by ensure_schema() which runs before migrations. This migration
verifies the schema looks correct and serves as the version anchor for future
migrations.

Historical migrations consolidated:
  V004: segment_scores_stats collection
  V005: vectors_track collections
  V006: applied_migrations collection
  V007: hot/cold vector split
  V008: cold vector normalization (vector_n backfill)
  V009: essentia tag key rename (_essentia* -> _v1_)
  V010: vram_promises collection
  V011: drop vram_promises TTL index (reverted V010 design)
  V012: drop gpu_warmup_claims (superseded)
  V013: rename song_tag_edges -> song_has_tags
  V014: ml_models, ml_model_outputs, tag_model_output collections
  V015: navidrome_song_map collection
  V016: file_states vertices + file_has_state edges
  V017: remove dead flat state fields from library_files
  V018: split global vectors into per-library collections
  V019: navidrome graph model + vector_promotion_locks
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

SCHEMA_VERSION_BEFORE: int = 0
SCHEMA_VERSION_AFTER: int = 1
DESCRIPTION: str = "Consolidated baseline schema verification"

# Collections that must exist after ensure_schema()
_REQUIRED_DOCUMENT_COLLECTIONS: list[str] = [
    "meta",
    "libraries",
    "library_files",
    "library_folders",
    "tags",
    "sessions",
    "calibration_state",
    "calibration_history",
    "health",
    "worker_claims",
    "ml_capacity_estimates",
    "ml_capacity_probe_locks",
    "worker_restart_policy",
    "segment_scores_stats",
    "applied_migrations",
    "vram_promises",
    "ml_models",
    "ml_model_outputs",
    "file_states",
    "navidrome_tracks",
    "navidrome_playcounts",
    "vector_promotion_locks",
]

_REQUIRED_EDGE_COLLECTIONS: list[str] = [
    "song_has_tags",
    "tag_model_output",
    "file_has_state",
    "has_nd_id",
    "has_plays",
]


def upgrade(db: DatabaseLike) -> None:
    """Verify that ensure_schema() created all expected collections."""
    missing: list[str] = []

    for name in _REQUIRED_DOCUMENT_COLLECTIONS:
        if not db.has_collection(name):
            missing.append(name)

    for name in _REQUIRED_EDGE_COLLECTIONS:
        if not db.has_collection(name):
            missing.append(name)

    if missing:
        msg = (
            f"Baseline verification failed: missing collections: {', '.join(missing)}. "
            "These should have been created by ensure_schema(). "
            "Check arango_bootstrap_comp.py."
        )
        raise RuntimeError(msg)

    logger.info(
        "Migration V001: Baseline verification passed — %d document + %d edge collections confirmed.",
        len(_REQUIRED_DOCUMENT_COLLECTIONS),
        len(_REQUIRED_EDGE_COLLECTIONS),
    )
'''

DB_RESET_AQL = [
    # Clear applied_migrations (old migration records are now meaningless)
    "FOR m IN applied_migrations REMOVE m IN applied_migrations",
    # Reset schema version to 0 so V001 baseline runs on next startup
    'UPSERT { key: "schema_version" } INSERT { key: "schema_version", value: "0" } UPDATE { value: "0" } IN meta',
]


def delete_old_migrations() -> list[str]:
    """Delete all historical migration files. Returns list of deleted filenames."""
    deleted: list[str] = []
    for filename in MIGRATION_FILES_TO_DELETE:
        path = MIGRATIONS_DIR / filename
        if path.exists():
            path.unlink()
            deleted.append(filename)
            print(f"  Deleted: {filename}")
        else:
            print(f"  Already gone: {filename}")
    return deleted


def create_baseline_migration() -> Path:
    """Create the consolidated V001 baseline migration."""
    target = MIGRATIONS_DIR / "V001_baseline.py"
    if target.exists():
        print(f"  WARNING: {target.name} already exists, overwriting")
    target.write_text(BASELINE_MIGRATION, encoding="utf-8")
    print(f"  Created: {target.name}")
    return target


def execute_db_reset() -> bool:
    """Connect to local dev ArangoDB and reset schema version + applied_migrations."""
    try:
        import os

        from arango import ArangoClient
    except ImportError:
        print("\n  ERROR: python-arango not installed. Run the AQL commands manually.")
        return False

    host = os.getenv("ARANGO_HOST", "http://127.0.0.1:8529")
    db_name = os.getenv("ARANGO_DB", "nomarr")
    username = os.getenv("ARANGO_USERNAME", "root")
    password = os.getenv("ARANGO_ROOT_PASSWORD", "")

    if not password:
        print(f"\n  ERROR: ARANGO_ROOT_PASSWORD not set. Cannot connect to {host}")
        return False

    try:
        client = ArangoClient(hosts=host)
        db = client.db(db_name, username=username, password=password)

        for aql in DB_RESET_AQL:
            db.aql.execute(aql)
            print(f"  Executed: {aql[:80]}...")

        print("  Database reset complete.")
        return True
    except Exception as exc:
        print(f"\n  ERROR: Failed to connect/execute: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolidate all migrations into a single baseline.")
    parser.add_argument(
        "--execute-db-reset",
        action="store_true",
        help="Also reset the local dev database schema version",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Migration Consolidation Script (Alpha)")
    print("=" * 60)

    # Step 1: Delete old migrations
    print("\n[1/3] Deleting historical migration files...")
    deleted = delete_old_migrations()
    print(f"  Total deleted: {len(deleted)}")

    # Step 2: Create baseline
    print("\n[2/3] Creating consolidated baseline migration...")
    create_baseline_migration()

    # Step 3: Database reset
    print("\n[3/3] Database schema version reset...")
    if args.execute_db_reset:
        execute_db_reset()
    else:
        print("  To reset an existing database, run these AQL queries:")
        print()
        for aql in DB_RESET_AQL:
            print(f"    {aql}")
        print()
        print("  Or re-run this script with --execute-db-reset")
        print("  Or just delete your ArangoDB volume for a clean start:")
        print("    cd docker && docker compose down -v && docker compose up -d")

    # Summary
    print("\n" + "=" * 60)
    print("Done! Migration history consolidated.")
    print()
    print("Before consolidation: 16 migration files (V004-V019)")
    print("After consolidation:  1 migration file  (V001_baseline)")
    print()
    print(
        textwrap.dedent("""\
        What changed:
          - Code schema version: 19 -> 1
          - ensure_schema() is a frozen baseline (update it to match current DB state)
          - V001 just verifies collections exist
          - Future migrations start at V002
          - New schema changes go in migration files ONLY (not ensure_schema)

        For your existing database, either:
          a) Run the AQL commands above (keeps your data)
          b) Nuke the volume: docker compose down -v (fresh start)
        """)
    )


if __name__ == "__main__":
    main()
