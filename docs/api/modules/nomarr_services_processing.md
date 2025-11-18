# nomarr.services.processing

API reference for `nomarr.services.processing`.

---

## Classes

### ProcessingService

Audio processing operations - shared by all interfaces.

**Methods:**

- `__init__(self, coordinator: 'ProcessingCoordinator | None' = None)`
- `get_worker_count(self) -> 'int'`
- `is_available(self) -> 'bool'`
- `process_batch(self, paths: 'list[str]', force: 'bool' = False) -> 'list[dict[str, Any]]'`
- `process_file(self, path: 'str', force: 'bool' = False) -> 'dict[str, Any]'`
- `shutdown(self) -> 'None'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
