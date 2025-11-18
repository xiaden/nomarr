# nomarr.services.workers.base

API reference for `nomarr.services.workers.base`.

---

## Classes

### BaseWorker

Generic background worker for queue processing.

**Methods:**

- `__init__(self, name: 'str', queue: 'ProcessingQueue', process_fn: 'Callable[[str, bool], dict[str, Any]]', db: 'Database', event_broker: 'Any', worker_id: 'int' = 0, interval: 'int' = 2)`
- `cancel(self) -> 'None'`
- `is_busy(self) -> 'bool'`
- `last_heartbeat(self) -> 'int'`
- `run(self) -> 'None'`
- `stop(self) -> 'None'`

---
