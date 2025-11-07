# DRY Refactoring - Action Plan

## Tomorrow's Work

### Phase 1: Create Helper Modules (Foundation)

**Location Decision**: Put helpers LOW in the dependency tree so everything can import them easily.

#### Option A: `nomarr/util.py` (NEW FILE - Recommended)
```
nomarr/
  util.py          ← New general utilities module
  config.py
  data/
    db.py
  core/
  interfaces/
```
- ✅ Nothing imports from util, everything imports util
- ✅ No circular dependencies
- ✅ Clear separation from domain logic

#### Option B: Extend existing low-level modules
- `nomarr/data/db.py` - Add `db_session()` context manager
- `nomarr/config.py` - Add config caching

### Helpers to Create

1. **`db_session()` context manager**
   ```python
   # nomarr/util.py or nomarr/data/db.py
   @contextmanager
   def db_session(db_path=None):
       """Auto-managed DB connection with cleanup."""
       if db_path is None:
           from nomarr.config import compose
           db_path = compose({})["db_path"]
       db = Database(db_path)
       try:
           yield db
       finally:
           db.close()
   ```

2. **`get_db_and_config()` for web endpoints**
   ```python
   # nomarr/interfaces/api/helpers.py (already exists!)
   @contextmanager
   def get_db_and_config():
       """Combined config+DB for web endpoints."""
       # Implementation from DRY_OPPORTUNITIES.md
   ```

3. **Cache compose() results**
   ```python
   # nomarr/config.py
   _config_cache = None
   
   def get_config(force_reload=False):
       """Cached config singleton."""
       # Lazy load once per process
   ```

### Files to Refactor (in order)

1. ✅ **DONE**: `nomarr/core/library_scanner.py` - Already DRY'd
2. **Next**: `nomarr/interfaces/api/endpoints/web.py` (834 lines, 30+ endpoints)
   - Split into separate routers by resource:
     - `web_auth.py` - login/logout
     - `web_processing.py` - process/batch-process
     - `web_queue.py` - queue operations
     - `web_admin.py` - admin operations  
     - `web_library.py` - library/scan operations
     - `web_analytics.py` - analytics endpoints
     - `web_navidrome.py` - navidrome config
3. **Then**: CLI commands (easy wins, just use `db_session()`)
4. **Maybe**: `nomarr/data/db.py` (709 lines) - Split if methods group naturally

### Success Metrics

- [ ] Reduce web.py from 834 → ~100 lines (router composition only)
- [ ] Eliminate ~350 lines of duplicate boilerplate
- [ ] All DB connections use context managers
- [ ] Config loaded once per process
- [ ] Zero breaking changes (backward compatible)

## Notes

- web.py keeps crashing network connection when analyzing (too big?)
- Focus on mechanical refactoring (low risk)
- Run tests after each file refactored
- Update `__init__.py` exports with `generate_inits.py`

---

**Status**: Ready to implement  
**Start with**: Create `db_session()` in `nomarr/data/db.py`  
**Then**: Refactor one web.py router at a time
