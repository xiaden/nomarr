"""
Command: manage_password — Manage admin password.
"""

from __future__ import annotations

import argparse
import getpass

from nomarr.config import compose
from nomarr.data.db import Database
from nomarr.interfaces.cli.ui import print_error, print_info, print_success


def cmd_manage_password(args: argparse.Namespace) -> int:
    """
    Manage admin password for web UI authentication.

    Subcommands:
    - show: Display current password hash
    - verify: Test if a password is correct
    - reset: Change the password

    Args:
        args: Parsed arguments

    Returns:
        Exit code (0 = success)
    """
    config = compose()
    db_path = config["db_path"]

    db = Database(db_path)
    service = KeyManagementService(db)

    try:
        if args.password_cmd == "show":
            return _show_password(service)
        elif args.password_cmd == "verify":
            return _verify_password(service)
        elif args.password_cmd == "reset":
            return _reset_password(service)
        else:
            print_error(f"Unknown password command: {args.password_cmd}")
            return 1

    finally:
        db.close()


def _show_password(service: KeyManagementService) -> int:
    """Show current password hash."""
    password_hash = service.get_admin_password_hash()

    if not password_hash:
        print_info("No admin password set")
        print_info("A password will be auto-generated on first API startup")
        return 0

    print_info("Current admin password hash:")
    print(password_hash)
    print()
    print_info("Password is stored as salted SHA-256 hash")
    print_info("To view the actual password, check container logs on first startup")
    return 0


def _verify_password(service: KeyManagementService) -> int:
    """Verify if a password is correct."""
    password_hash = service.get_admin_password_hash()

    if not password_hash:
        print_error("No admin password set yet")
        return 1

    password = getpass.getpass("Enter password to verify: ")

    if service.verify_password(password, password_hash):
        print_success("✓ Password is correct")
        return 0
    else:
        print_error("✗ Password is incorrect")
        return 1


def _reset_password(service: KeyManagementService) -> int:
    """Reset admin password."""
    print_info("Reset admin password for web UI")
    print()

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

    # Hash and store
    password_hash = service.hash_password(password1)
    service.db.set_meta("admin_password_hash", password_hash)

    print()
    print_success("✓ Admin password updated successfully")
    print_info("You can now log in to the web UI with the new password")
    print_info("Web UI: http://<server>:8356/")

    return 0
