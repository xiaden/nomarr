# nomarr.interfaces.api.endpoints.public

API reference for `nomarr.interfaces.api.endpoints.public`.

---

## Functions

### get_globals()

Get global instances (db, queue, services, etc.) from application.

### get_info()

Get comprehensive system info: config, models, queue status, worker app.

### get_status(job_id: 'int')

Get job status by ID.

### list_jobs(limit: 'int' = 50, offset: 'int' = 0, status: 'str | None' = None)

List jobs with pagination and optional status filtering.

### tag_audio(req: 'TagRequest')

Queue audio file(s) for tagging.

---
