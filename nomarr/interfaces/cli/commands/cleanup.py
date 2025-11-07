"""
Cleanup command: Remove old finished jobs from the queue.
"""

from __future__ import annotations

import argparse

from nomarr.config import compose
from nomarr.data.queue import JobQueue
from nomarr.interfaces.cli.ui import InfoPanel, print_info, show_spinner
from nomarr.interfaces.cli.utils import get_db
from nomarr.services.queue import QueueService


def cmd_cleanup(args: argparse.Namespace) -> int:
    """
    Remove old finished jobs from the queue to prevent bloat.
    """
    cfg = compose({})
    db = get_db(cfg)
    try:
        max_age_hours = args.hours if args.hours is not None else int(cfg.get("cleanup_age_hours", 168))

        # Task to perform cleanup using service
        def _do_cleanup(service: QueueService, hours: int) -> int:
            return service.cleanup_old_jobs(max_age_hours=hours)

        # Create service
        queue = JobQueue(db)
        queue_service = QueueService(db, queue)

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
    finally:
        db.close()
