# nomarr.services.health_monitor

API reference for `nomarr.services.health_monitor`.

---

## Classes

### HealthMonitor

Universal worker health monitor.

**Methods:**

- `__init__(self, check_interval: 'int' = 10)`
- `register_worker(self, worker: 'Any', on_death: 'Callable[[], None] | None' = None, name: 'str | None' = None) -> 'None'`
- `start(self) -> 'None'`
- `stop(self) -> 'None'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
