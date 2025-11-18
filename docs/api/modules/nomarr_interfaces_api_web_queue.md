# nomarr.interfaces.api.web.queue

API reference for `nomarr.interfaces.api.web.queue`.

---

## Classes

### AdminResetRequest

Request to reset stuck/error jobs.

### RemoveRequest

Request to remove jobs from queue.

---

## Functions

### web_admin_cache_refresh() -> dict[str, str]

Refresh model cache (web UI proxy).

### web_admin_cleanup(max_age_hours: int = 168, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Remove old completed/error jobs (web UI proxy).

### web_admin_clear_all(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Clear all jobs from queue including running ones (web UI).

### web_admin_clear_completed(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Clear completed jobs from queue (web UI).

### web_admin_clear_errors(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Clear error jobs from queue (web UI).

### web_admin_flush(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Remove all completed/error jobs (web UI proxy).

### web_admin_remove(request: nomarr.interfaces.api.web.queue.RemoveRequest, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Remove jobs from queue (web UI proxy).

### web_admin_reset(request: nomarr.interfaces.api.web.queue.AdminResetRequest, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, typing.Any]

Reset stuck/error jobs to pending (web UI proxy).

### web_queue_depth(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service)) -> dict[str, typing.Any]

Get queue depth statistics (web UI proxy).

### web_status(job_id: int, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service)) -> dict[str, typing.Any]

Get status of a specific job (web UI proxy).

---
