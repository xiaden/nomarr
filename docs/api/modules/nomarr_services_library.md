# nomarr.services.library

API reference for `nomarr.services.library`.

---

## Classes

### LibraryService

Library scanning operations - shared by all interfaces.

**Methods:**

- `__init__(self, db: 'Database', namespace: 'str', library_path: 'str | None' = None, worker: 'LibraryScanWorker | None' = None)`
- `cancel_scan(self) -> 'bool'`
- `get_scan_history(self, limit: 'int' = 10) -> 'list[dict[str, Any]]'`
- `get_status(self) -> 'dict[str, Any]'`
- `is_configured(self) -> 'bool'`
- `start_scan(self, namespace: 'str | None' = None, progress_callback: 'Callable[[int, int], None] | None' = None, background: 'bool' = False) -> 'int'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
