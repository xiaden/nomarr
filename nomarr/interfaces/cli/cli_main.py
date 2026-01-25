#!/usr/bin/env python3
"""
Main CLI entry point with argument parser and command dispatch.
"""

from __future__ import annotations

import argparse

from nomarr.interfaces.cli.commands.cache_refresh_cli import cmd_cache_refresh
from nomarr.interfaces.cli.commands.cleanup_cli import cmd_cleanup
from nomarr.interfaces.cli.commands.manage_password_cli import cmd_manage_password


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="nom",
        description="Nomarr - Audio auto-tagging for Lidarr using Essentia ML models",
        epilog="Examples:\n"
        "  nom cleanup                                # Remove orphaned entities\n"
        "  nom cleanup --dry-run                      # Preview orphaned entities\n"
        "  nom cache-refresh                          # Rebuild model cache\n"
        "  nom manage-password reset                  # Change admin password",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = parser.add_subparsers(
        dest="cmd",
        title="commands",
        description="Available commands (use 'nom <command> --help' for command-specific help)",
    )

    # cleanup: Remove orphaned entities
    subparser = sub.add_parser("cleanup", help="Remove orphaned entities (artists, albums, etc.) with no songs")
    subparser.add_argument("--dry-run", action="store_true", help="show what would be deleted without deleting")
    subparser.set_defaults(func=cmd_cleanup)

    # cache-refresh: Rebuild predictor cache
    subparser = sub.add_parser("cache-refresh", help="Rebuild model cache (use after adding/removing models)")
    subparser.set_defaults(func=cmd_cache_refresh)

    # manage-password: Admin password management
    subparser = sub.add_parser("manage-password", help="Manage admin password for web UI")
    password_sub = subparser.add_subparsers(dest="password_cmd", title="password commands", required=True)

    # manage-password show: Display password hash
    ps = password_sub.add_parser("show", help="Display current password hash")
    ps.set_defaults(func=cmd_manage_password)

    # manage-password verify: Test password
    ps = password_sub.add_parser("verify", help="Verify if a password is correct")
    ps.set_defaults(func=cmd_manage_password)

    # manage-password reset: Change password
    ps = password_sub.add_parser("reset", help="Change admin password")
    ps.set_defaults(func=cmd_manage_password)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # If no command provided, show help
    if args.cmd is None:
        parser.print_help()
        return 0

    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
