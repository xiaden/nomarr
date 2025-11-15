"""
Remove command: Remove jobs from the queue.
"""

from __future__ import annotations

import argparse
from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import nomarr.app as app
from nomarr.interfaces.cli.ui import InfoPanel, print_error, print_info, print_success, print_warning

if TYPE_CHECKING:
    from nomarr.services.queue import QueueService


@contextmanager
def worker_paused() -> Generator[None, None, None]:
    """Context manager to pause worker during removal operations."""
    worker_service = app.application.services["worker"]
    was_enabled = worker_service.is_enabled()

    if was_enabled:
        print_info("Pausing worker and waiting for active jobs to complete...")
        worker_service.disable()

    try:
        yield
    finally:
        if was_enabled:
            worker_service.enable()
            print_info("Worker resumed")


def _validate_statuses(statuses: list[str]) -> tuple[bool, str]:
    """Validate status filter. Returns (is_valid, error_message)."""
    valid = {"pending", "running", "done", "error"}
    bad = [s for s in statuses if s not in valid]
    if bad:
        return False, f"Invalid status(es): {', '.join(bad)}"
    if "running" in statuses:
        return False, "Cannot remove 'running' jobs"
    return True, ""


def _remove_all_jobs(queue_service: QueueService) -> int:
    """Remove all non-running jobs. Returns status code."""
    stats = queue_service.get_status()
    count = stats.get("pending", 0) + stats.get("completed", 0) + stats.get("errors", 0)

    if count == 0:
        print_warning("No jobs to remove")
        return 0

    content = f"""[bold]Statuses:[/bold] pending, error, done
[bold]Jobs to remove:[/bold] {count}"""
    InfoPanel.show("Removing All Jobs", content, "yellow")

    removed = queue_service.remove_jobs(all=True)
    print_success(f"Removed {removed} job(s)")
    return 0


def _remove_jobs_by_status(queue_service: QueueService, statuses: list[str]) -> int:
    """Remove jobs by status filter. Returns status code."""
    is_valid, error = _validate_statuses(statuses)
    if not is_valid:
        print_error(error)
        return 2

    # Get count before removal
    total_count = 0
    status_map = {"pending": "pending", "done": "completed", "error": "errors"}
    for status in statuses:
        stats = queue_service.get_status()
        status_key = status_map.get(status, status)
        total_count += stats.get(status_key, 0)

    if total_count == 0:
        print_warning(f"No jobs found with status: {', '.join(statuses)}")
        return 0

    content = f"""[bold]Statuses:[/bold] {", ".join(statuses)}
[bold]Jobs to remove:[/bold] {total_count}"""
    InfoPanel.show("Removing Jobs", content, "yellow")

    # Remove jobs by status
    total_removed = 0
    for status in statuses:
        removed = queue_service.remove_jobs(status=status)
        total_removed += removed

    print_success(f"Removed {total_removed} job(s) with status: {', '.join(statuses)}")
    return 0


def _remove_single_job(queue_service: QueueService, job_id: int) -> int:
    """Remove single job by ID. Returns status code."""
    job_data = queue_service.get_job(job_id)
    if not job_data:
        print_error(f"Job {job_id} not found")
        return 1

    if job_data["status"] == "running":
        print_error("Cannot remove running job")
        return 2

    # Show job details before removal
    status_color = {"pending": "yellow", "running": "blue", "done": "green", "error": "red"}.get(
        job_data["status"], "white"
    )

    content = f"""[bold]Path:[/bold] {job_data["file_path"]}
[bold]Status:[/bold] [{status_color}]{job_data["status"]}[/{status_color}]
[bold]Created:[/bold] {job_data.get("created_at") or "N/A"}"""

    InfoPanel.show(f"Removing Job {job_id}", content, "red")

    queue_service.remove_jobs(job_id=job_id)
    print_success(f"Job {job_id} removed from queue")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """
    Remove job(s) from the queue.
    Supports single job removal, bulk flush by status, or remove all.
    """
    if not app.application.is_running():
        print_error("Application is not running. Start the server first.")
        return 1

    try:
        queue_service = app.application.services["queue"]

        with worker_paused():
            # Mode 1: Remove all non-running jobs (--all flag)
            if hasattr(args, "all") and args.all:
                return _remove_all_jobs(queue_service)

            # Mode 2: Remove by status filter (--status flag)
            if hasattr(args, "status") and args.status:
                statuses = [args.status] if isinstance(args.status, str) else args.status
                return _remove_jobs_by_status(queue_service, statuses)

            # Mode 3: Remove single job by ID
            if not hasattr(args, "job_id") or not args.job_id:
                print_error("Must specify job_id, --all, or --status")
                return 1

            return _remove_single_job(queue_service, int(args.job_id))

    except Exception as e:
        print_error(f"Error removing jobs: {e}")
        return 1
