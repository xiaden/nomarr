# nomarr.workflows.scan_library

API reference for `nomarr.workflows.scan_library`.

---

## Functions

### scan_library_workflow(db: 'Database', library_path: 'str', namespace: 'str', progress_callback: 'Callable[[int, int], None] | None' = None, scan_id: 'int | None' = None, auto_tag: 'bool' = False, ignore_patterns: 'str' = '') -> 'dict[str, Any]'

Scan a music library directory and update the database.

### update_library_file_from_tags(db: 'Database', file_path: 'str', namespace: 'str', tagged_version: 'str | None' = None, calibration: 'dict[str, str] | None' = None) -> 'None'

Update library database with current file metadata and tags.

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
