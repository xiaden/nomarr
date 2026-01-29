#!/usr/bin/env python3
"""Drop old calibration collections after histogram refactor.

This script removes the legacy collections:
- calibration_queue (replaced by stateless computation)
- calibration_runs (replaced by calibration_state + calibration_history)

Run this AFTER verifying the histogram-based calibration system works.
This is a ONE-WAY migration. Backup your database first if needed.
"""

from nomarr.services.domain.config_svc import ConfigService

from nomarr.persistence.db import Database


def drop_old_collections(db: Database) -> None:
    """Drop legacy calibration collections."""
    collections_to_drop = ["calibration_queue", "calibration_runs"]

    for coll_name in collections_to_drop:
        if db.db.has_collection(coll_name):
            print(f"Dropping collection: {coll_name}")
            db.db.delete_collection(coll_name)
            print(f"  ✓ Dropped {coll_name}")
        else:
            print(f"  • Collection {coll_name} does not exist (already dropped or never created)")


def main() -> None:
    """Main entry point."""
    print("=" * 80)
    print("Drop Old Calibration Collections")
    print("=" * 80)
    print()
    print("This script will drop:")
    print("  - calibration_queue")
    print("  - calibration_runs")
    print()
    print("These collections are replaced by:")
    print("  - calibration_state (histogram-based generation)")
    print("  - calibration_history (drift tracking)")
    print()

    response = input("Continue? [y/N]: ").strip().lower()
    if response != "y":
        print("Aborted.")
        return

    print()
    print("Loading config and connecting to database...")
    config_svc = ConfigService()
    db = Database(config_svc.arango)

    print("Dropping collections...")
    drop_old_collections(db)

    print()
    print("=" * 80)
    print("Migration complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
