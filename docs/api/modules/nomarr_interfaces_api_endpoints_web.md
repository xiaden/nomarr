# nomarr.interfaces.api.endpoints.web

API reference for `nomarr.interfaces.api.endpoints.web`.

---

## Classes

### AdminResetRequest

!!! abstract "Usage Documentation"

### BatchProcessRequest

!!! abstract "Usage Documentation"

### CalibrationRequest

!!! abstract "Usage Documentation"

### ConfigUpdateRequest

Request model for updating configuration values.

### LoginRequest

!!! abstract "Usage Documentation"

### LoginResponse

!!! abstract "Usage Documentation"

### LogoutResponse

!!! abstract "Usage Documentation"

### ProcessRequest

!!! abstract "Usage Documentation"

### RemoveRequest

!!! abstract "Usage Documentation"

---

## Functions

### apply_calibration_to_library()

Queue all library files for recalibration.

### clear_calibration_queue()

Clear all pending and completed recalibration jobs.

### generate_calibration(request: 'CalibrationRequest')

Generate min-max scale calibration from library tags.

### get_calibration_status()

Get current recalibration queue status.

### get_config(_session: 'dict' = Depends(verify_session))

Get current configuration values (user-editable subset).

### get_state()

Get application state for web endpoints.

### login(request: 'LoginRequest')

Authenticate with admin password and receive a session token.

### logout(creds=Depends(verify_session))

Invalidate the current session token (logout).

### update_config(request: 'ConfigUpdateRequest', _session: 'dict' = Depends(verify_session))

Update a configuration value in the database.

### web_admin_cache_refresh()

Refresh model cache (web UI proxy).

### web_admin_cleanup(max_age_hours: 'int' = 168)

Remove old completed/error jobs (web UI proxy).

### web_admin_clear_all()

Clear all jobs from queue including running ones (web UI).

### web_admin_clear_completed()

Clear completed jobs from queue (web UI).

### web_admin_clear_errors()

Clear error jobs from queue (web UI).

### web_admin_flush()

Remove all completed/error jobs (web UI proxy).

### web_admin_remove(request: 'RemoveRequest')

Remove jobs from queue (web UI proxy).

### web_admin_reset(request: 'AdminResetRequest')

Reset stuck/error jobs to pending (web UI proxy).

### web_admin_restart()

Restart the API server (useful after config changes).

### web_admin_worker_pause()

Pause the worker (web UI proxy).

### web_admin_worker_resume()

Resume the worker (web UI proxy).

### web_analytics_mood_distribution()

Get mood tag distribution.

### web_analytics_tag_co_occurrences(tag: 'str', limit: 'int' = 10)

Get mood value co-occurrences and genre/artist relationships.

### web_analytics_tag_correlations(top_n: 'int' = 20)

Get VALUE-based correlation matrix for mood values, genres, and attributes.

### web_analytics_tag_frequencies(limit: 'int' = 50)

Get tag frequency statistics.

### web_batch_process(request: 'BatchProcessRequest')

Add multiple paths to the database queue for processing (web UI proxy).

### web_health()

Health check endpoint (web UI proxy).

### web_info()

Get system info (web UI proxy).

### web_library_stats()

Get library statistics (total files, artists, albums, duration).

### web_list(limit: 'int' = 50, offset: 'int' = 0, status: 'str | None' = None)

List jobs with pagination and filtering (web UI proxy).

### web_navidrome_config()

Generate Navidrome TOML configuration (web UI proxy).

### web_navidrome_playlist_generate(request: 'dict')

Generate Navidrome Smart Playlist (.nsp) from query.

### web_navidrome_playlist_preview(request: 'dict')

Preview Smart Playlist query results.

### web_navidrome_preview()

Get preview of tags for Navidrome config generation (web UI proxy).

### web_navidrome_templates_generate()

Generate all playlist templates as a batch.

### web_navidrome_templates_list()

Get list of all available playlist templates.

### web_process(request: 'ProcessRequest')

Process a single file synchronously (web UI proxy).

### web_queue_depth()

Get queue depth statistics (web UI proxy).

### web_show_tags(path: 'str')

Read tags from an audio file (web UI proxy).

### web_sse_status(token: 'str')

Server-Sent Events endpoint for real-time system status updates.

### web_status(job_id: 'int')

Get status of a specific job (web UI proxy).

---
