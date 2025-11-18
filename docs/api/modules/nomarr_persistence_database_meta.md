# nomarr.persistence.database.meta

API reference for `nomarr.persistence.database.meta`.

---

## Classes

### MetaOperations

Operations for the meta key-value store table.

**Methods:**

- `__init__(self, conn: sqlite3.Connection) -> None`
- `delete(self, key: str) -> None`
- `get(self, key: str) -> str | None`
- `get_by_prefix(self, prefix: str) -> dict[str, str]`
- `set(self, key: str, value: str) -> None`

---
