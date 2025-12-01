"""Queue components - domain logic for queue operations."""

from nomarr.components.queue.queue_cleanup_comp import (
    cleanup_old_jobs,
    clear_all_jobs,
    clear_completed_jobs,
    clear_error_jobs,
    clear_jobs_by_status,
    remove_job,
    reset_error_jobs,
    reset_stuck_jobs,
)
from nomarr.components.queue.queue_dequeue_comp import (
    get_next_job,
    mark_job_complete,
    mark_job_error,
)
from nomarr.components.queue.queue_enqueue_comp import (
    check_file_needs_processing,
    enqueue_file,
    enqueue_file_checked,
)
from nomarr.components.queue.queue_status_comp import (
    get_active_jobs,
    get_job,
    get_queue_depth,
    get_queue_stats,
    list_jobs,
)

__all__ = [
    # Enqueue operations
    "enqueue_file",
    "enqueue_file_checked",
    "check_file_needs_processing",
    # Dequeue operations
    "get_next_job",
    "mark_job_complete",
    "mark_job_error",
    # Status operations
    "get_queue_stats",
    "get_queue_depth",
    "get_job",
    "list_jobs",
    "get_active_jobs",
    # Cleanup operations
    "remove_job",
    "clear_jobs_by_status",
    "clear_completed_jobs",
    "clear_error_jobs",
    "clear_all_jobs",
    "reset_stuck_jobs",
    "reset_error_jobs",
    "cleanup_old_jobs",
]
