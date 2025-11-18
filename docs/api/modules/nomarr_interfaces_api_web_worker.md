# nomarr.interfaces.api.web.worker

API reference for `nomarr.interfaces.api.web.worker`.

---

## Functions

### web_admin_restart() -> dict[str, str]

Restart the API server (useful after config changes).

### web_admin_worker_pause(db: nomarr.persistence.db.Database = Depends(get_database), worker_pool: list[typing.Any] = Depends(get_worker_pool), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, str]

Pause the worker (web UI proxy).

### web_admin_worker_resume(worker_service: Optional[Any] = Depends(get_worker_service), worker_pool: list[typing.Any] = Depends(get_worker_pool), event_broker: Optional[Any] = Depends(get_event_broker)) -> dict[str, str]

Resume the worker (web UI proxy).

---
