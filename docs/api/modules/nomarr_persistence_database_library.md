# nomarr.persistence.database.library

API reference for `nomarr.persistence.database.library`.

---

## Classes

### LibraryOperations

Operations for library_files (music library) and library_queue (scan tracking) tables.

**Methods:**

- `__init__(self, conn: sqlite3.Connection) -> None`
- `clear_library_data(self) -> None`
- `count_running_scans(self) -> int`
- `create_library_scan(self) -> int`
- `delete_library_file(self, path: str) -> None`
- `get_all_library_paths(self) -> list[str]`
- `get_latest_scan_id(self) -> int | None`
- `get_library_file(self, path: str) -> dict[str, typing.Any] | None`
- `get_library_scan(self, scan_id: int) -> dict[str, typing.Any] | None`
- `get_library_stats(self) -> dict[str, typing.Any]`
- `get_running_scan(self) -> dict[str, typing.Any] | None`
- `get_scan_by_id(self, scan_id: int) -> dict[str, typing.Any] | None`
- `list_library_files(self, limit: int = 100, offset: int = 0, artist: str | None = None, album: str | None = None) -> tuple[list[dict[str, typing.Any]], int]`
- `list_library_scans(self, limit: int = 10) -> list[dict[str, typing.Any]]`
- `list_scans(self, limit: int = 10) -> list[dict[str, typing.Any]]`
- `mark_file_tagged(self, path: str, tagged_version: str) -> None`
- `reset_running_library_scans(self) -> int`
- `update_library_scan(self, scan_id: int, status: str | None = None, files_scanned: int | None = None, files_added: int | None = None, files_updated: int | None = None, files_removed: int | None = None, error_message: str | None = None) -> None`
- `upsert_library_file(self, path: str, file_size: int, modified_time: int, duration_seconds: float | None = None, artist: str | None = None, album: str | None = None, title: str | None = None, genre: str | None = None, year: int | None = None, track_number: int | None = None, tags_json: str | None = None, nom_tags: str | None = None, calibration: str | None = None, last_tagged_at: int | None = None) -> int`

---

## Functions

### now_ms() -> int

Get current timestamp in milliseconds.

---
