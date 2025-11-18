# nomarr.services.analytics

API reference for `nomarr.services.analytics`.

---

## Classes

### AnalyticsService

Service for tag analytics and statistics.

**Methods:**

- `__init__(self, db: 'Database') -> 'None'`
- `get_artist_tag_profile(self, artist: 'str', namespace: 'str' = 'nom', limit: 'int' = 20) -> 'dict[str, Any]'`
- `get_mood_distribution(self, namespace: 'str' = 'nom') -> 'dict[str, Any]'`
- `get_mood_value_co_occurrences(self, mood_value: 'str', namespace: 'str' = 'nom', limit: 'int' = 20) -> 'dict[str, Any]'`
- `get_tag_correlation_matrix(self, namespace: 'str' = 'nom', top_n: 'int' = 20) -> 'dict[str, Any]'`
- `get_tag_frequencies(self, namespace: 'str' = 'nom', limit: 'int' = 50) -> 'dict[str, Any]'`

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
