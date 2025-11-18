# nomarr.services.worker

API reference for `nomarr.services.worker`.

---

## Classes

### WorkerService

Worker management operations - shared by all interfaces.

**Methods:**

- `__init__(self, db: 'Database', queue: 'ProcessingQueue', processor_coord: 'ProcessingCoordinator | None' = None, default_enabled: 'bool' = True, worker_count: 'int' = 1, poll_interval: 'int' = 2)`
- `cleanup_orphaned_jobs(self) -> 'int'`
- `disable(self) -> 'None'`
- `enable(self) -> 'None'`
- `get_status(self) -> 'dict[str, Any]'`
- `is_enabled(self) -> 'bool'`
- `pause(self) -> 'dict[str, Any]'`
- `resume(self, event_broker: 'Any | None' = None) -> 'dict[str, Any]'`
- `start_workers(self, event_broker: 'Any | None' = None) -> 'list[BaseWorker]'`
- `stop_all_workers(self) -> 'None'`
- `wait_until_idle(self, timeout: 'int' = 60, poll_interval: 'float' = 0.5) -> 'bool'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
