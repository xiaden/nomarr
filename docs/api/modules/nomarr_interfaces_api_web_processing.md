# nomarr.interfaces.api.web.processing

API reference for `nomarr.interfaces.api.web.processing`.

---

## Classes

### BatchProcessRequest

Request to batch process multiple paths.

### ProcessRequest

Request to process a single file.

---

## Functions

### web_batch_process(request: nomarr.interfaces.api.web.processing.BatchProcessRequest, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service)) -> dict[str, typing.Any]

Add multiple paths to the database queue for processing (web UI proxy).

### web_list(limit: int = 50, offset: int = 0, status: str | None = None, queue_service: nomarr.services.queue.QueueService = Depends(get_queue_service)) -> dict[str, typing.Any]

List jobs with pagination and filtering (web UI proxy).

### web_process(request: nomarr.interfaces.api.web.processing.ProcessRequest, processor_coord: nomarr.services.coordinator.ProcessingCoordinator | None = Depends(get_processor_coordinator)) -> dict[str, typing.Any]

Process a single file synchronously (web UI proxy).

---
