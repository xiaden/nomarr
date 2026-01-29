"""Command: manage_password — Manage admin password.

Architecture:
- Uses CLI bootstrap service to get KeyManagementService instance
- Does NOT depend on running Application (separate process)
- Does NOT access Database or persistence internals directly
- Calls service methods for all password operations
"""

from __future__ import annotations

import getpass
from typing import TYPE_CHECKING

from nomarr.interfaces.cli.cli_ui import print_error, print_info, print_success
from nomarr.services.infrastructure.cli_bootstrap_svc import get_keys_service

if TYPE_CHECKING:
    import argparse

    from nomarr.services.infrastructure.keys_svc import KeyManagementService


def cmd_manage_password(args: argparse.Namespace) -> int:
    """Manage admin password for web UI authentication.

    Subcommands:
    - show: Display current password hash
    - verify: Test if a password is correct
    - reset: Change the password

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 = success)

    Note:
        This command runs in a separate process from the server and uses
        CLI bootstrap to get a standalone KeyManagementService instance.

    """
    # Get standalone service instance (no running Application required)
    service = get_keys_service()

    if args.password_cmd == "show":
        return _show_password(service)
    if args.password_cmd == "verify":
        return _verify_password(service)
    if args.password_cmd == "reset":
        return _reset_password(service)
    print_error(f"Unknown password command: {args.password_cmd}")
    return 1


def _show_password(service: KeyManagementService) -> int:
    """Show current password hash."""
    try:
        service.get_admin_password_hash()
    except RuntimeError:
        # Password not found in DB
        print_info("No admin password set")
        print_info("A password will be auto-generated on first application startup")
        return 0

    print_info("Current admin password hash:")
    print_info("Password is stored as bcrypt hash")
    print_info("To view the actual password, check container logs on first startup")
    return 0


def _verify_password(service: KeyManagementService) -> int:
    """Verify if a password is correct."""
    try:
        password_hash = service.get_admin_password_hash()
    except RuntimeError:
        # Password not found in DB
        print_error("No admin password set yet")
        return 1

    password = getpass.getpass("Enter password to verify: ")

    if service.verify_password(password, password_hash):
        print_success("✓ Password is correct")
        return 0
    print_error("✗ Password is incorrect")
    return 1


def _reset_password(service: KeyManagementService) -> int:
    """Reset admin password using service method (no direct DB access)."""
    print_info("Reset admin password for web UI")

    # Get new password
    while True:
        password1 = getpass.getpass("Enter new password: ")
        if len(password1) < 8:
            print_error("Password must be at least 8 characters")
            continue

        password2 = getpass.getpass("Confirm new password: ")

        if password1 != password2:
            print_error("Passwords do not match")
            continue

        break

    # Use service method to reset password (hashes and stores internally)
    service.reset_admin_password(password1)

    print_success("✓ Admin password updated successfully")
    print_info("You can now log in to the web UI with the new password")
    print_info("Web UI: http://<server>:8356/")

    return 0
