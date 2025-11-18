# nomarr.interfaces.api.web.info

API reference for `nomarr.interfaces.api.web.info`.

---

## Functions

### web_health(queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service), processor_coord: nomarr.services.coordinator.ProcessingCoordinator | None = Depends(get_processor_coordinator)) -> dict[str, typing.Any]

Health check endpoint (web UI proxy).

### web_info(cfg: dict = Depends(get_config), worker_service: Optional[Any] = Depends(get_worker_service)) -> dict[str, typing.Any]

Get system info (web UI proxy).

---
