#!/usr/bin/env python3
"""
Main CLI entry point with argument parser and command dispatch.
"""

from __future__ import annotations

import argparse

from nomarr.interfaces.cli.commands.admin_reset import cmd_admin_reset
from nomarr.interfaces.cli.commands.cache_refresh import cmd_cache_refresh
from nomarr.interfaces.cli.commands.cleanup import cmd_cleanup
from nomarr.interfaces.cli.commands.manage_password import cmd_manage_password
from nomarr.interfaces.cli.commands.recover_internal_key import cmd_recover_internal_key
from nomarr.interfaces.cli.commands.remove import cmd_remove


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    p = argparse.ArgumentParser(
        prog="nom",
        description="Nomarr - Audio auto-tagging for Lidarr using Essentia ML models",
        epilog="Examples:\n"
        "  nom cleanup --hours 168                    # Remove old jobs (7 days)\n"
        "  nom admin-reset --stuck                    # Reset stuck jobs\n"
        "  nom cache-refresh                          # Rebuild model cache\n"
        "  nom remove --status error                  # Remove failed jobs\n"
        "  nom manage-password reset                  # Change admin password\n"
        "  nom recover-internal-key --force           # Regenerate internal key (emergency)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    sub = p.add_subparsers(
        dest="cmd",
        title="commands",
        description="Available commands (use 'nom <command> --help' for command-specific help)",
    )

    # remove: Remove jobs from queue
    s = sub.add_parser("remove", help="Remove job(s) from the queue")
    s.add_argument("job_id", nargs="?", help="specific job ID to remove")
    s.add_argument("--all", action="store_true", help="remove all non-running jobs")
    s.add_argument("--status", help="remove jobs with status: pending, error, or done")
    s.set_defaults(func=cmd_remove)

    # cleanup: Remove old finished jobs
    s = sub.add_parser("cleanup", help="Remove old completed jobs from database")
    s.add_argument("--hours", type=int, default=168, help="remove jobs older than N hours (default: 168 = 1 week)")
    s.set_defaults(func=cmd_cleanup)

    # cache-refresh: Rebuild predictor cache
    s = sub.add_parser("cache-refresh", help="Rebuild model cache (use after adding/removing models)")
    s.set_defaults(func=cmd_cache_refresh)

    # admin-reset: Reset stuck or error jobs
    s = sub.add_parser("admin-reset", help="Reset stuck or failed jobs back to pending state")
    s.add_argument("--stuck", action="store_true", help="reset jobs stuck in 'running' state (after crashes)")
    s.add_argument("--errors", action="store_true", help="reset all failed jobs to retry them")
    s.add_argument("--force", action="store_true", help="skip confirmation prompt")
    s.set_defaults(func=cmd_admin_reset)

    # manage-password: Admin password management
    s = sub.add_parser("manage-password", help="Manage admin password for web UI")
    password_sub = s.add_subparsers(dest="password_cmd", title="password commands", required=True)

    # manage-password show: Display password hash
    ps = password_sub.add_parser("show", help="Display current password hash")
    ps.set_defaults(func=cmd_manage_password)

    # manage-password verify: Test password
    ps = password_sub.add_parser("verify", help="Verify if a password is correct")
    ps.set_defaults(func=cmd_manage_password)

    # manage-password reset: Change password
    ps = password_sub.add_parser("reset", help="Change admin password")
    ps.set_defaults(func=cmd_manage_password)

    # recover-internal-key: Emergency CLI recovery
    s = sub.add_parser("recover-internal-key", help="Regenerate internal API key (emergency recovery)")
    s.add_argument("--force", action="store_true", help="skip confirmation prompt")
    s.set_defaults(func=cmd_recover_internal_key)

    return p


def main(argv: list[str] | None = None) -> int:
    """Main entry point for CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # If no command provided, show help
    if args.cmd is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
