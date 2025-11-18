# nomarr.interfaces.cli.utils

API reference for `nomarr.interfaces.cli.utils`.

---

## Functions

### api_call(path: 'str', method: 'str' = 'GET', body: 'dict | None' = None) -> 'dict'

Minimal HTTP helper to call the API using config + DB-stored API key.

### format_duration(seconds: 'float') -> 'str'

Format seconds into human readable: 2d 5h 30m

### format_tag_summary(tags: 'dict') -> 'str'

Format a brief summary of notable tags (mood tags) for display.

---
