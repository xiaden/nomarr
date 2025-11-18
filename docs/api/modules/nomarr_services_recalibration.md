# nomarr.services.recalibration

API reference for `nomarr.services.recalibration`.

---

## Classes

### RecalibrationService

Service for recalibrating library files with updated calibration values.

**Methods:**

- `__init__(self, database: 'Database', worker: 'RecalibrationWorker | None' = None)`
- `clear_queue(self) -> 'int'`
- `enqueue_file(self, file_path: 'str') -> 'int'`
- `enqueue_library(self, paths: 'list[str]') -> 'int'`
- `get_status(self) -> 'dict[str, int]'`
- `is_worker_alive(self) -> 'bool'`
- `is_worker_busy(self) -> 'bool'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
