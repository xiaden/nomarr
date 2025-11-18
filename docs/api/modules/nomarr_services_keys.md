# nomarr.services.keys

API reference for `nomarr.services.keys`.

---

## Classes

### KeyManagementService

Service for managing API keys, passwords, and sessions.

**Methods:**

- `__init__(self, db: 'Database')`
- `cleanup_expired_sessions(self) -> 'int'`
- `create_session(self) -> 'str'`
- `get_admin_password_hash(self) -> 'str'`
- `get_api_key(self) -> 'str'`
- `get_or_create_admin_password(self, config_password: 'str | None' = None) -> 'str'`
- `get_or_create_api_key(self) -> 'str'`
- `hash_password(password: 'str') -> 'str'`
- `invalidate_session(self, session_token: 'str') -> 'None'`
- `load_sessions_from_db(self) -> 'int'`
- `reset_admin_password(self, new_password: 'str') -> 'None'`
- `rotate_api_key(self) -> 'str'`
- `validate_session(self, session_token: 'str') -> 'bool'`
- `verify_password(password: 'str', password_hash: 'str') -> 'bool'`

---

## Constants

### SESSION_TIMEOUT_SECONDS

```python
SESSION_TIMEOUT_SECONDS = 86400
```

---
