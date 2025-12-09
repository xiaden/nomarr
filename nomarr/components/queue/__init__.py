"""
Queue package.
"""

from .queue_cleanup_comp import (
    UnsupportedQueueOperationError,
    cleanup_old_jobs,
    clear_all_jobs,
    clear_completed_jobs,
    clear_error_jobs,
    clear_jobs_by_status,
    remove_job,
    reset_error_jobs,
    reset_stuck_jobs,
)
from .queue_dequeue_comp import get_next_job, mark_job_complete, mark_job_error
from .queue_enqueue_comp import (
    check_file_needs_processing,
    enqueue_file,
    enqueue_file_checked,
)
from .queue_status_comp import (
    get_active_jobs,
    get_job,
    get_queue_depth,
    get_queue_stats,
    list_jobs,
)

__all__ = [
    "UnsupportedQueueOperationError",
    "check_file_needs_processing",
    "cleanup_old_jobs",
    "clear_all_jobs",
    "clear_completed_jobs",
    "clear_error_jobs",
    "clear_jobs_by_status",
    "enqueue_file",
    "enqueue_file_checked",
    "get_active_jobs",
    "get_job",
    "get_next_job",
    "get_queue_depth",
    "get_queue_stats",
    "list_jobs",
    "mark_job_complete",
    "mark_job_error",
    "remove_job",
    "reset_error_jobs",
    "reset_stuck_jobs",
]
