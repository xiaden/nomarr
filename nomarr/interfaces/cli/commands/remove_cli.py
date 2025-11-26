"""
Remove command: Remove jobs from the queue.
"""

from __future__ import annotations

import argparse

import nomarr.app as app
from nomarr.interfaces.cli.cli_ui import InfoPanel, print_error, print_info, print_success, print_warning


def cmd_remove(args: argparse.Namespace) -> int:
    """
    Remove job(s) from the queue.
    Supports single job removal, bulk flush by status, or remove all.
    """
    # Check if Application is running
    if not app.application.is_running():
        print_error("Application is not running. Start the server first.")
        return 1

    try:
        # Use services from running Application
        queue_service = app.application.services["queue"]
        worker_service = app.application.services["worker"]

        # Check if worker is currently enabled (preserve state)
        was_enabled = worker_service.is_enabled()

        # Disable worker during removal (waits for active jobs to complete)
        if was_enabled:
            print_info("Pausing worker and waiting for active jobs to complete...")
            worker_service.disable()

        try:
            # Mode 1: Remove all non-running jobs (--all flag)
            if hasattr(args, "all") and args.all:
                # Get count before removal
                stats = queue_service.get_status()
                count = stats.counts.get("pending", 0) + stats.counts.get("done", 0) + stats.counts.get("error", 0)

                if count == 0:
                    print_warning("No jobs to remove")
                    return 0

                content = f"""[bold]Statuses:[/bold] pending, error, done
[bold]Jobs to remove:[/bold] {count}"""
                InfoPanel.show("Removing All Jobs", content, "yellow")

                # Remove all non-running jobs
                removed = queue_service.remove_jobs(all=True)
                print_success(f"Removed {removed} job(s)")
                return 0

            # Mode 2: Remove by status filter (--status flag)
            if hasattr(args, "status") and args.status:
                statuses = [args.status] if isinstance(args.status, str) else args.status
                valid = {"pending", "running", "done", "error"}
                bad = [s for s in statuses if s not in valid]
                if bad:
                    print_error(f"Invalid status(es): {', '.join(bad)}")
                    return 2
                if "running" in statuses:
                    print_error("Cannot remove 'running' jobs")
                    return 2

                # Get count before removal
                total_count = 0
                for status in statuses:
                    stats = queue_service.get_status()
                    # Map status name to counts key
                    total_count += stats.counts.get(status, 0)

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

            # Mode 3: Remove single job by ID
            if not hasattr(args, "job_id") or not args.job_id:
                print_error("Must specify job_id, --all, or --status")
                return 1

            job_data = queue_service.get_job(int(args.job_id))
            if not job_data:
                print_error(f"Job {args.job_id} not found")
                return 1
            if job_data.status == "running":
                print_error("Cannot remove running job")
                return 2

            # Show job details before removal
            status_color = {"pending": "yellow", "running": "blue", "done": "green", "error": "red"}.get(
                job_data.status, "white"
            )

            content = f"""[bold]Path:[/bold] {job_data.path}
[bold]Status:[/bold] [{status_color}]{job_data.status}[/{status_color}]
[bold]Started:[/bold] {job_data.started_at or "N/A"}"""

            InfoPanel.show(f"Removing Job {args.job_id}", content, "red")

            # Remove using service
            queue_service.remove_jobs(job_id=int(args.job_id))
            print_success(f"Job {args.job_id} removed from queue")
            return 0

        finally:
            # Restore worker state if we disabled it
            if was_enabled:
                worker_service.enable()
                print_info("Worker resumed")

    except Exception as e:
        print_error(f"Error removing jobs: {e}")
        return 1
