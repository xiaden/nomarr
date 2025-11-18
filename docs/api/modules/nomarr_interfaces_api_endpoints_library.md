# nomarr.interfaces.api.endpoints.library

API reference for `nomarr.interfaces.api.endpoints.library`.

---

## Functions

### cancel_library_scan(_session: 'dict' = Depends(verify_session))

Cancel the currently running library scan.

### clear_library_data(_session: 'dict' = Depends(verify_session))

Clear all library data (files, tags, scans) to force a fresh rescan.

### get_library_scan_history(limit: 'int' = 10, _session: 'dict' = Depends(verify_session))

Get library scan history.

### get_library_scan_status(_session: 'dict' = Depends(verify_session))

Get current library scan worker status.

### get_library_stats(_session: 'dict' = Depends(verify_session))

Get library statistics (total files, artists, albums, duration).

### pause_library_scanner(_session: 'dict' = Depends(verify_session))

Pause the library scanner (stop processing new scans).

### resume_library_scanner(_session: 'dict' = Depends(verify_session))

Resume the library scanner.

### start_library_scan(_session: 'dict' = Depends(verify_session))

Start a new library scan (queues it for background processing).

---
