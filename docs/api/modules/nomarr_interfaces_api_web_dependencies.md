# nomarr.interfaces.api.web.dependencies

API reference for `nomarr.interfaces.api.web.dependencies`.

---

## Functions

### get_config() -> 'dict[str, Any]'

Get configuration dict.

### get_database() -> 'Database'

Get Database instance.

### get_event_broker() -> 'Any | None'

Get EventBroker instance (may be None).

### get_processor_coordinator() -> 'ProcessingCoordinator | None'

Get ProcessingCoordinator instance (may be None).

### get_queue() -> 'Any'

Get ProcessingQueue instance.

### get_queue_service() -> 'QueueService'

Get QueueService instance.

### get_worker_pool() -> 'list[Any]'

Get worker pool list.

### get_worker_service() -> 'Any | None'

Get WorkerService instance (may be None).

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
