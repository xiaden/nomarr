"""
Admin-reset command: Reset stuck or error jobs to pending.
"""

from __future__ import annotations

import argparse

from nomarr.config import compose
from nomarr.data.queue import JobQueue
from nomarr.interfaces.cli.ui import InfoPanel, print_error, print_info, print_success
from nomarr.interfaces.cli.utils import get_db
from nomarr.services.queue import QueueService


def cmd_admin_reset(args: argparse.Namespace) -> int:
    """
    Admin command to reset jobs to pending status.
    Supports resetting stuck running jobs (--stuck) or error jobs (--errors).
    """
    cfg = compose({})
    db = get_db(cfg)
    try:
        # Create service
        queue = JobQueue(db)
        queue_service = QueueService(db, queue)

        # Determine which reset mode to use
        if hasattr(args, "stuck") and args.stuck:
            # Get count of stuck jobs
            stats = queue_service.get_status()
            count = stats.get("running", 0)

            if count == 0:
                print_info("No running jobs found")
                return 0

            content = f"""[yellow]WARNING:[/yellow] This will reset ALL running jobs to pending status.
[bold]Running jobs:[/bold] {count}

This should only be used if jobs are stuck (e.g., after a crash).
"""
            InfoPanel.show("Reset Stuck Jobs", content, "yellow")

            if not args.force:
                response = input("Continue? (yes/no): ").strip().lower()
                if response not in ("yes", "y"):
                    print_info("Cancelled")
                    return 0

            # Reset using service
            reset_count = queue_service.reset_jobs(stuck=True, errors=False)
            print_success(f"Reset {reset_count} stuck job(s) to pending")
            return 0

        elif hasattr(args, "errors") and args.errors:
            # Get count of error jobs
            stats = queue_service.get_status()
            count = stats.get("errors", 0)

            if count == 0:
                print_info("No error jobs found")
                return 0

            content = f"""[yellow]INFO:[/yellow] This will reset ALL error jobs to pending status.
[bold]Error jobs:[/bold] {count}

These jobs will be retried by the worker.
"""
            InfoPanel.show("Reset Error Jobs", content, "blue")

            if not args.force:
                response = input("Continue? (yes/no): ").strip().lower()
                if response not in ("yes", "y"):
                    print_info("Cancelled")
                    return 0

            # Reset using service
            reset_count = queue_service.reset_jobs(stuck=False, errors=True)
            print_success(f"Reset {reset_count} error job(s) to pending")
            return 0

        else:
            print_error("Must specify either --stuck or --errors")
            return 1

    finally:
        db.close()
