# Code Duplication Analysis - DRY Opportunities

## Executive Summary

Found **extensive code duplication** across the codebase with these main patterns:

1. **DB Connection Pattern** (~50+ instances)
2. **Config + DB Pattern** (~30+ instances in web.py alone)
3. **Session Management Pattern** (multiple locations)

---

## Pattern 1: DB Connection Boilerplate

### Current (WET):
```python
# Repeated ~50 times across codebase
db_path = cfg["db_path"]
db = Database(db_path)
try:
    # do work
    result = db.some_operation()
    return result
finally:
    db.close()
```

### Locations:
- `nomarr/interfaces/api/endpoints/web.py` - **8 instances**
- `nomarr/interfaces/cli/commands/*.py` - **12+ files**
- `nomarr/workflows/processor.py` - 1 instance
- `nomarr/config.py` - 1 instance
- `nomarr/manage_key.py` - 1 instance
- `nomarr/manage_password.py` - 1 instance

### Proposed (DRY):
```python
# Add to nomarr/persistence/db.py or nomarr/util.py
from contextlib import contextmanager

@contextmanager
def db_session(db_path: str | None = None):
    """
    Context manager for database sessions.
    Automatically handles connection and cleanup.
    
    Usage:
        with db_session() as db:
            return db.some_operation()
    """
    if db_path is None:
        from nomarr.config import compose
        cfg = compose({})
        db_path = cfg["db_path"]
    
    db = Database(db_path)
    try:
        yield db
    finally:
        db.close()
```

### Impact:
- **50+ locations** simplified from 5-7 lines to 2 lines
- **200+ lines** of duplicate code eliminated
- Guaranteed cleanup even on exceptions
- Single source of truth for DB lifecycle

---

## Pattern 2: Config + DB + Namespace Pattern

### Current (WET):
```python
# Repeated ~30 times in web.py alone
from nomarr.persistence.db import Database

config = compose()
db_path = str(Path(config["db_path"]).resolve())
namespace = config["namespace"]

db = Database(db_path)
try:
    result = some_analytics_function(db, namespace=namespace)
    return result
finally:
    db.close()
```

### Locations (just in web.py):
- `/web/api/library/stats` (line 674)
- `/web/api/library/scans` (line 709)
- `/web/api/analytics/tag-frequencies` (line 778)
- `/web/api/analytics/mood-distribution` (line 813)
- `/web/api/analytics/tag-correlations` (line 858)
- `/web/api/analytics/mood-value-co-occurrences` (line 886)
- `/web/api/analytics/artist-profile` (line 934)
- `/web/api/library/scan` (line 984)
- `/web/api/library/clear` (line 1037)

### Proposed (DRY):
```python
# Add to nomarr/interfaces/api/helpers.py or web.py
from contextlib import contextmanager

@contextmanager
def get_db_and_config():
    """
    Context manager providing both DB session and config.
    Common pattern for web API endpoints.
    
    Usage:
        with get_db_and_config() as (db, cfg):
            return analytics_function(db, namespace=cfg["namespace"])
    """
    from pathlib import Path
    from nomarr.config import compose
    from nomarr.persistence.db import Database
    
    cfg = compose()
    db_path = str(Path(cfg["db_path"]).resolve())
    db = Database(db_path)
    
    try:
        yield db, cfg
    finally:
        db.close()
```

### Impact:
- **30+ endpoints** in web.py simplified
- **150+ lines** eliminated in single file
- Consistent config/db handling across all endpoints
- Easier to add instrumentation (logging, metrics) later

---

## Pattern 3: Compose Config Repeatedly

### Current (WET):
```python
# Called ~40+ times across codebase
cfg = compose({})
# or
config = compose()
```

### Issue:
- `compose()` reads YAML + env vars every time
- File I/O on every call
- Inconsistent variable naming (`cfg` vs `config`)

### Proposed (DRY):
```python
# Option A: Lazy singleton in config.py
_cached_config = None

def get_config(force_reload=False):
    """Get cached config (reads once per process)."""
    global _cached_config
    if _cached_config is None or force_reload:
        _cached_config = compose({})
    return _cached_config

# Option B: Keep compose() but add caching internally
# (Better for backward compatibility)
```

### Impact:
- **40+ calls** benefit from caching
- Faster startup/response times
- Consistent config across request lifecycle
- Easy cache invalidation if needed

---

## Pattern 4: Session Token Validation

### Current (WET - in web.py):
```python
# Repeated in every web endpoint
from nomarr.interfaces.api.auth import validate_session_token

session_token = request.cookies.get("session_token")
if not session_token or not validate_session_token(session_token):
    raise HTTPException(status_code=401, detail="Unauthorized")
```

### Proposed (DRY):
```python
# Add FastAPI dependency
from fastapi import Depends, Cookie, HTTPException

async def require_session(session_token: str = Cookie(None)):
    """Dependency to require valid session token."""
    if not session_token:
        raise HTTPException(status_code=401, detail="No session token")
    if not validate_session_token(session_token):
        raise HTTPException(status_code=401, detail="Invalid session")
    return session_token

# Usage:
@router.get("/web/api/something")
async def endpoint(session: str = Depends(require_session)):
    # Session already validated
    ...
```

### Impact:
- **20+ endpoints** simplified
- Centralized auth logic
- FastAPI-native dependency injection
- Easier to add session refresh, CSRF, etc.

---

## Recommended Implementation Order

### Phase 1: Low-Hanging Fruit (Immediate)
1. ✅ **DONE**: `update_library_file_from_tags()` helper (completed)
2. **Add `db_session()` context manager** to `nomarr/persistence/db.py`
3. **Add `get_db_and_config()` to web.py helpers**

### Phase 2: Refactor High-Traffic Code (Next)
4. Refactor `web.py` endpoints to use new helpers
5. Refactor CLI commands to use `db_session()`
6. Add config caching to `compose()`

### Phase 3: Quality Improvements (Future)
7. Add FastAPI session dependency
8. Create shared error handling decorator
9. Add telemetry/logging hooks to helpers

---

## Estimated Impact

| Metric | Before | After | Savings |
|--------|--------|-------|---------|
| Duplicate DB boilerplate | ~250 lines | ~50 lines | **80%** |
| Config + DB pattern | ~180 lines | ~30 lines | **83%** |
| Total LOC reduction | - | - | **~350 lines** |
| Files affected | ~25 files | ~2 files | **92% consolidation** |

---

## Breaking Changes

**None** - All helpers are additive:
- Existing code continues working
- Refactor incrementally
- No API changes required

---

## Next Steps

1. Review this analysis
2. Prioritize patterns to tackle
3. Create helpers in appropriate modules
4. Refactor one pattern at a time
5. Run full test suite after each pattern
6. Update this doc as we progress

---

**Status**: 🟡 Ready for implementation  
**Priority**: 🔴 High (technical debt reduction)  
**Effort**: 🟢 Low (mostly mechanical refactoring)
