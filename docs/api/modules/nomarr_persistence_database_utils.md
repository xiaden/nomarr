# nomarr.persistence.database.utils

API reference for `nomarr.persistence.database.utils`.

---

## Functions

### count_and_delete(db: 'Database', table: 'str', where_clause: 'str' = '', params: 'tuple' = ()) -> 'int'

Count matching rows, then delete them.

### count_and_update(db: 'Database', table: 'str', set_clause: 'str', where_clause: 'str' = '', params: 'tuple' = ()) -> 'int'

Count matching rows, then update them.

### get_queue_stats(db: 'Database') -> 'dict[str, int]'

Get queue statistics (counts by status).

### safe_count(db: 'Database', query: 'str', params: 'tuple' = ()) -> 'int'

Safely execute a COUNT query and return the result.

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
