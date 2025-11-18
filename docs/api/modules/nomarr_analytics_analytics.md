# nomarr.analytics.analytics

API reference for `nomarr.analytics.analytics`.

---

## Functions

### compute_artist_tag_profile(artist: 'str', file_count: 'int', namespace_prefix: 'str', tag_rows: 'Sequence[tuple[str, str, str]]', limit: 'int' = 20) -> 'dict[str, Any]'

Compute tag profile for an artist from raw tag data.

### compute_mood_distribution(mood_rows: 'Sequence[tuple[str, str, str]]') -> 'dict[str, Any]'

Compute mood distribution from raw mood tag data.

### compute_mood_value_co_occurrences(mood_value: 'str', matching_file_ids: 'set[int]', mood_tag_rows: 'Sequence[tuple[int, str, str]]', genre_rows: 'Sequence[tuple[str, int]]', artist_rows: 'Sequence[tuple[str, int]]', limit: 'int' = 20) -> 'dict[str, Any]'

Compute mood value co-occurrence statistics from raw data.

### compute_tag_correlation_matrix(namespace: 'str', top_n: 'int', mood_tag_rows: 'Sequence[tuple[int, str, str]]', tier_tag_keys: 'Sequence[str]', tier_tag_rows: 'dict[str, Sequence[tuple[int, str]]]') -> 'dict[str, Any]'

Compute VALUE-based correlation matrix from raw tag data.

### compute_tag_frequencies(namespace_prefix: 'str', total_files: 'int', nom_tag_rows: 'Sequence[tuple[str, int]]', artist_rows: 'Sequence[tuple[str, int]]', genre_rows: 'Sequence[tuple[str, int]]', album_rows: 'Sequence[tuple[str, int]]') -> 'dict[str, Any]'

Compute frequency counts from raw tag data.

---
