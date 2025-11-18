# nomarr.services.workers.recalibration

API reference for `nomarr.services.workers.recalibration`.

---

## Classes

### RecalibrationWorker

Background worker that applies calibration to library files.

**Methods:**

- `__init__(self, db: 'Database', models_dir: 'str', namespace: 'str' = 'nom', version_tag_key: 'str' = 'nom_version', poll_interval: 'int' = 2, calibrate_heads: 'bool' = False)`
- `is_alive_check(self) -> 'bool'`
- `is_busy(self) -> 'bool'`
- `run(self) -> 'None'`
- `stop(self) -> 'None'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
