# nomarr.persistence.database.queue

API reference for `nomarr.persistence.database.queue`.

---

## Classes

### QueueOperations

Operations for the tag_queue table (ML tagging job queue).

**Methods:**

- `__init__(self, conn: sqlite3.Connection) -> None`
- `clear_old_jobs(self, max_age_hours: int = 168) -> None`
- `delete_job(self, job_id: int) -> int`
- `delete_jobs_by_status(self, statuses: list[str]) -> int`
- `enqueue(self, path: str, force: bool = False) -> int`
- `get_active_jobs(self, limit: int = 50) -> list[dict[str, typing.Any]]`
- `get_next_pending_job(self) -> dict[str, typing.Any] | None`
- `get_recent_done_jobs_timing(self, limit: int = 5) -> list[tuple[int, int]]`
- `get_running_job_ids(self) -> list[int]`
- `job_status(self, job_id: int) -> dict[str, typing.Any] | None`
- `list_jobs(self, limit: int = 25, offset: int = 0, status: str | None = None) -> tuple[list[dict[str, typing.Any]], int]`
- `queue_depth(self) -> int`
- `queue_stats(self) -> dict[str, int]`
- `reset_error_jobs(self) -> int`
- `reset_running_to_pending(self) -> int`
- `reset_stuck_jobs(self) -> int`
- `update_job(self, job_id: int, status: str, error_message: str | None = None, results: dict[str, typing.Any] | None = None) -> None`

---

## Functions

### now_ms() -> int

Get current timestamp in milliseconds.

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
