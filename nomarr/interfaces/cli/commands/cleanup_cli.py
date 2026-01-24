"""
Cleanup command: Remove orphaned entities from the metadata graph.

Architecture:
- Uses CLI bootstrap service to get MetadataService instance
- Does NOT depend on running Application (separate process)
- Does NOT access Database or workflows directly
- Calls service methods for all cleanup operations
"""

from __future__ import annotations

import argparse

from nomarr.interfaces.cli.cli_ui import InfoPanel, print_error
from nomarr.services.infrastructure.cli_bootstrap_svc import get_metadata_service


def cmd_cleanup(args: argparse.Namespace) -> int:
    """
    Remove orphaned entities (artists, albums, genres, labels, years) that have no songs.
    Runs standalone without requiring the app to be running.
    """
    # Get standalone service instance (no running Application required)
    service = get_metadata_service()

    try:
        dry_run = getattr(args, "dry_run", False)

        result = service.cleanup_orphaned_entities(dry_run=dry_run)

        total_deleted = result.get("total_deleted", 0)
        deleted_counts = result.get("deleted_counts", {})

        if isinstance(total_deleted, int) and total_deleted > 0:
            if isinstance(deleted_counts, dict):
                details = "\n".join([f"[bold]{k.title()}:[/bold] {v}" for k, v in deleted_counts.items() if v > 0])
            else:
                details = ""
            content = f"""[bold]Total Deleted:[/bold] {total_deleted}

{details}"""
            InfoPanel.show("Entity Cleanup Complete", content, "green")
        else:
            print_error("No orphaned entities found")

        return 0
    except Exception as e:
        print_error(f"Error during cleanup: {e}")
        return 1
