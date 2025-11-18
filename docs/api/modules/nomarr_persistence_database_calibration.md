# nomarr.persistence.database.calibration

API reference for `nomarr.persistence.database.calibration`.

---

## Classes

### CalibrationOperations

Operations for calibration queue and calibration run tracking.

**Methods:**

- `__init__(self, conn: 'sqlite3.Connection')`
- `clear_calibration_queue(self) -> 'int'`
- `complete_calibration_job(self, job_id: 'int') -> 'None'`
- `enqueue_calibration(self, file_path: 'str') -> 'int'`
- `fail_calibration_job(self, job_id: 'int', error_message: 'str') -> 'None'`
- `get_calibration_status(self) -> 'dict[str, int]'`
- `get_latest_calibration_run(self, model_name: 'str', head_name: 'str') -> 'dict[str, Any] | None'`
- `get_next_calibration_job(self) -> 'tuple[int, str] | None'`
- `get_reference_calibration_run(self, model_name: 'str', head_name: 'str') -> 'dict[str, Any] | None'`
- `insert_calibration_run(self, model_name: 'str', head_name: 'str', version: 'int', file_count: 'int', p5: 'float', p95: 'float', range_val: 'float', reference_version: 'int | None' = None, apd_p5: 'float | None' = None, apd_p95: 'float | None' = None, srd: 'float | None' = None, jsd: 'float | None' = None, median_drift: 'float | None' = None, iqr_drift: 'float | None' = None, is_stable: 'bool' = False) -> 'int'`
- `list_calibration_runs(self, model_name: 'str | None' = None, head_name: 'str | None' = None, limit: 'int' = 100) -> 'list[dict[str, Any]]'`
- `reset_running_calibration_jobs(self) -> 'int'`

---

## Functions

### now_ms() -> 'int'

Return current timestamp in milliseconds.

---
