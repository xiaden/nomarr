# nomarr.services.coordinator

API reference for `nomarr.services.coordinator`.

---

## Classes

### ProcessingCoordinator

Coordinates job submission to the process pool.

**Methods:**

- `__init__(self, worker_count: 'int' = 1, event_broker=None)`
- `publish_event(self, topic: 'str', event_data: 'dict[str, Any]')`
- `start(self)`
- `stop(self)`
- `submit(self, path: 'str', force: 'bool') -> 'dict[str, Any]'`

---

## Functions

### process_file_wrapper(path: 'str', force: 'bool') -> 'dict[str, Any]'

Wrapper for process_file that runs in a separate process.

---
