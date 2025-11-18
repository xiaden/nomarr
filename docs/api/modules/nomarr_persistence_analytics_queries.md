# nomarr.persistence.analytics_queries

API reference for `nomarr.persistence.analytics_queries`.

---

## Functions

### fetch_artist_tag_profile_data(db: 'Database', artist: 'str', namespace: 'str') -> 'dict[str, Any]'

Fetch raw tag data for a specific artist.

### fetch_mood_distribution_data(db: 'Database', namespace: 'str') -> 'list[tuple[str, str, str]]'

Fetch raw mood tag data for distribution analysis.

### fetch_mood_value_co_occurrence_data(db: 'Database', mood_value: 'str', namespace: 'str') -> 'dict[str, Any]'

Fetch raw data for mood value co-occurrence analysis.

### fetch_tag_correlation_data(db: 'Database', namespace: 'str', top_n: 'int') -> 'dict[str, Any]'

Fetch raw data for tag correlation analysis.

### fetch_tag_frequencies_data(db: 'Database', namespace: 'str', limit: 'int') -> 'dict[str, Any]'

Fetch raw data for tag frequency analysis.

---

## Constants

### TYPE_CHECKING

```python
TYPE_CHECKING = False
```

---
