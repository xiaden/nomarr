# nomarr.interfaces.api.endpoints.admin

API reference for `nomarr.interfaces.api.endpoints.admin`.

---

## Functions

### admin_cache_refresh()

Force rebuild of the predictor cache (discover heads and load missing).

### admin_calibration_history(model: 'str | None' = None, head: 'str | None' = None, limit: 'int' = 100)

Get calibration history with drift metrics.

### admin_cleanup_queue(max_age_hours: 'int' = 168)

Remove old finished jobs from the queue (done/error status).

### admin_flush_queue(payload: 'FlushRequest' = Body(None))

Flush jobs by status (default: pending + error). Cannot flush running jobs.

### admin_pause_worker()

Pause the background worker (stops processing new jobs).

### admin_remove_job(payload: 'RemoveJobRequest')

Remove a single job by ID (cannot remove if running).

### admin_resume_worker()

Resume the background worker (starts processing again).

### admin_retag_all()

Mark all tagged files for re-tagging (requires calibrate_heads=true).

### admin_run_calibration()

Generate calibrations with drift tracking (requires calibrate_heads=true).

### get_globals()

Get global instances (db, queue, services, etc.) from application.

---
