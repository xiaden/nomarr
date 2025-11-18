# nomarr.services.workers.scanner

API reference for `nomarr.services.workers.scanner`.

---

## Classes

### LibraryScanWorker

Background worker that performs library scans asynchronously.

**Methods:**

- `__init__(self, db: 'Database', library_path: 'str', namespace: 'str', poll_interval: 'int' = 5, auto_tag: 'bool' = False, ignore_patterns: 'str' = '')`
- `cancel_scan(self)`
- `get_status(self) -> 'dict'`
- `pause(self)`
- `request_scan(self) -> 'int'`
- `resume(self)`
- `start(self)`
- `stop(self)`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
