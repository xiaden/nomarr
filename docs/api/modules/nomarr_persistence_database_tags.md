# nomarr.persistence.database.tags

API reference for `nomarr.persistence.database.tags`.

---

## Classes

### TagOperations

Operations for the library_tags table (normalized tag storage).

**Methods:**

- `__init__(self, conn: sqlite3.Connection) -> None`
- `get_file_tags(self, file_id: int) -> dict[str, typing.Any]`
- `get_file_tags_by_prefix(self, file_id: int, prefix: str) -> dict[str, typing.Any]`
- `get_tag_summary(self, tag_key: str) -> dict[str, typing.Any]`
- `get_tag_type_stats(self, tag_key: str) -> dict[str, typing.Any]`
- `get_tag_values(self, tag_key: str, limit: int = 1000) -> list[tuple[str, str]]`
- `get_unique_tag_keys(self) -> list[str]`
- `upsert_file_tags(self, file_id: int, tags: dict[str, typing.Any]) -> None`

---
