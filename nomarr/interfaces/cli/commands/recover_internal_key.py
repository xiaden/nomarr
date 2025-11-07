"""
Command: recover-internal-key — Regenerate internal API key for CLI recovery.

This command is for emergency recovery when the CLI cannot connect to the API.
It regenerates the internal key and propagates it to state.
"""

from __future__ import annotations

import argparse

from nomarr.config import compose
from nomarr.data.db import Database
from nomarr.interfaces.cli.ui import print_error, print_info, print_success, print_warning
from nomarr.services.keys import KeyManagementService


def cmd_recover_internal_key(args: argparse.Namespace) -> int:
    """
    Regenerate internal API key for CLI recovery.

    This is an emergency recovery command for when:
    - The API is not responding
    - The internal key is corrupted or lost
    - The CLI cannot authenticate with the API

    WARNING: This will invalidate the current internal key.
    The API must be restarted after running this command.

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 = success)
    """
    if not args.force:
        print_warning("⚠ WARNING: This will regenerate the internal API key")
        print_warning("The API must be restarted after this operation")
        print_warning("")
        print_info("Use --force to confirm this operation")
        return 1

    config = compose()
    db_path = config["db_path"]

    db = Database(db_path)
    service = KeyManagementService(db)

    try:
        # Rotate internal key
        new_key = service.rotate_internal_key()

        print_success("✓ Internal API key regenerated successfully")
        print()
        print_info("New internal key:")
        print(new_key)
        print()
        print_warning("⚠ You must restart the API for this change to take effect:")
        print_info("  docker compose restart nomarr")
        print()
        print_info("The CLI will use the new key automatically on next run")

        return 0

    except Exception as e:
        print_error(f"Failed to regenerate internal key: {e}")
        return 1

    finally:
        db.close()
