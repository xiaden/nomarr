# nomarr.interfaces.api.web.analytics

API reference for `nomarr.interfaces.api.web.analytics`.

---

## Functions

### web_analytics_mood_distribution(db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get mood tag distribution.

### web_analytics_tag_co_occurrences(tag: str, limit: int = 10, db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get mood value co-occurrences and genre/artist relationships.

### web_analytics_tag_correlations(top_n: int = 20, db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get VALUE-based correlation matrix for mood values, genres, and attributes.

### web_analytics_tag_frequencies(limit: int = 50, db: nomarr.persistence.db.Database = Depends(get_database)) -> dict[str, typing.Any]

Get tag frequency statistics.

---
