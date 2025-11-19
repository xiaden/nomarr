"""
Cleanup command: Remove old finished jobs from the queue.
"""

from __future__ import annotations

import argparse

import nomarr.app as app
from nomarr.interfaces.cli.ui import InfoPanel, print_error, print_info, show_spinner


def cmd_cleanup(args: argparse.Namespace) -> int:
    """
    Remove old finished jobs from the queue to prevent bloat.
    """
    # Check if Application is running
    if not app.application.is_running():
        print_error("Application is not running. Start the server first.")
        return 1

    try:
        # Get max age from args (default 168 hours = 1 week)
        max_age_hours = args.hours if args.hours is not None else 168

        # Task to perform cleanup using service
        def _do_cleanup(service, hours: int) -> int:
            result: int = service.cleanup_old_jobs(max_age_hours=hours)
            return result

        # Use service from running Application
        queue_service = app.application.services["queue"]

        # Run with spinner
        count = show_spinner(
            f"Cleaning up jobs older than {max_age_hours} hours...",
            _do_cleanup,
            queue_service,
            max_age_hours,
        )

        if count > 0:
            content = f"""[bold]Max Age:[/bold] {max_age_hours} hours
[bold]Jobs Removed:[/bold] {count}"""
            InfoPanel.show("Cleanup Complete", content, "green")
        else:
            print_info(f"No jobs older than {max_age_hours} hours found")

        return 0
    except Exception as e:
        print_error(f"Error during cleanup: {e}")
        return 1
