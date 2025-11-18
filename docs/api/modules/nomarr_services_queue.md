# nomarr.services.queue

API reference for `nomarr.services.queue`.

---

## Classes

### Job

Represents a single job in the processing queue.

**Methods:**

- `__init__(self, **row)`
- `to_dict(self) -> 'dict[str, Any]'`

### ProcessingQueue

Thread-safe data access layer for the ML processing queue table.

**Methods:**

- `__init__(self, db: 'Database')`
- `add(self, path: 'str', force: 'bool' = False) -> 'int'`
- `delete(self, job_id: 'int') -> 'int'`
- `delete_by_status(self, statuses: 'list[str]') -> 'int'`
- `depth(self) -> 'int'`
- `get(self, job_id: 'int') -> 'Job | None'`
- `list_jobs(self, limit: 'int' = 25, offset: 'int' = 0, status: 'str | None' = None) -> 'tuple[list[Job], int]'`
- `mark_done(self, job_id: 'int', results: 'dict[str, Any] | None' = None) -> 'None'`
- `mark_error(self, job_id: 'int', error_message: 'str') -> 'None'`
- `reset_error_jobs(self) -> 'int'`
- `reset_stuck_jobs(self) -> 'int'`
- `start(self, job_id: 'int') -> 'None'`
- `update_status(self, job_id: 'int', status: 'str', **kwargs) -> 'None'`

### QueueService

Queue management operations - shared by all interfaces.

**Methods:**

- `__init__(self, queue: 'ProcessingQueue')`
- `add_files(self, paths: 'str | list[str]', force: 'bool' = False, recursive: 'bool' = True) -> 'dict[str, Any]'`
- `cleanup_old_jobs(self, max_age_hours: 'int' = 24) -> 'int'`
- `get_depth(self) -> 'int'`
- `get_job(self, job_id: 'int') -> 'dict[str, Any] | None'`
- `get_status(self) -> 'dict[str, int]'`
- `list_jobs(self, limit: 'int' = 50, offset: 'int' = 0, status: 'str | None' = None) -> 'dict[str, Any]'`
- `publish_queue_update(self, event_broker: 'Any | None') -> 'None'`
- `remove_jobs(self, job_id: 'int | None' = None, status: 'str | None' = None, all: 'bool' = False) -> 'int'`
- `reset_jobs(self, stuck: 'bool' = False, errors: 'bool' = False) -> 'int'`
- `wait_for_job_completion(self, job_id: 'int', timeout: 'int') -> 'dict[str, Any]'`

---
