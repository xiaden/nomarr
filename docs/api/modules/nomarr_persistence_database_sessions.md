# nomarr.persistence.database.sessions

API reference for `nomarr.persistence.database.sessions`.

---

## Classes

### SessionOperations

Operations for the sessions table (Web UI session persistence).

**Methods:**

- `__init__(self, conn: sqlite3.Connection) -> None`
- `cleanup_expired(self) -> int`
- `create(self, session_token: str, expiry: float) -> None`
- `delete(self, session_token: str) -> None`
- `get(self, session_token: str) -> float | None`
- `load_all(self) -> dict[str, float]`

---
