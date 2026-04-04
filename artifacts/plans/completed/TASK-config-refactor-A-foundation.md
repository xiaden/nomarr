# Task: Config Refactor — DB as Source of Truth

## Problem Statement

`ConfigService` has a broken read/write contract that causes real user-facing bugs (e.g., Navidrome credentials set via web UI don't take effect until restart).

**Current broken flow:**
- `_compose()` merges defaults → YAML → ENV → DB on first `get()` call, caches forever
- `set_config_value()` writes to DB but never invalidates the cache
- `get()` returns stale startup values for the lifetime of the process
- Docstring claims "reload capability" but `reload()` doesn't exist
- `set_config_value()` and `_load_db_config()` create throwaway `Database()` instances
- 3 separate whitelist sets can drift (`_ALLOWED_CONFIG_KEYS`, two inline `editable_keys` in `config_if.py`)

**Desired architecture:**
1. **Bootstrap (startup only):** Load defaults → YAML → ENV overrides → write merged result to DB meta table (single throwaway DB connection)
2. **Runtime init:** Read all config from DB → populate a mutable in-memory cache (same throwaway connection as bootstrap)
3. **Runtime read:** Always from cache (fast, no recomposition)
4. **Runtime write:** Mutate cache → cache setter triggers DB write (throwaway connection, infrequent)

DB is the durable store. Cache is the fast read path. The setter keeps them in sync. No multi-source recomposition at runtime. No frozen snapshots.

## Phases

### Phase 1: Implement bootstrap and cache init with shared connection

- [x] Add `_bootstrap_and_load(self) -> None` private method that opens ONE throwaway `Database()` connection and performs both bootstrap seed and cache load in sequence
    **Notes:** Single connection for both operations eliminates the two-throwaway problem. Bootstrap uses `db.meta.get_by_prefix("config_")` once to batch-read existing keys, then only writes keys NOT already in DB (preserves user's web UI changes across restarts). After seeding, same connection reads all `config_*` keys back into `self._cache`.
      Added `_bootstrap_and_load()` at line 232. Opens one throwaway Database(), batch-reads existing keys, seeds missing keys, loads all config_* back into `self._cache`. Includes fallback to file/env config if DB unavailable. Also added `_parse_db_value()` static method for type parsing.
- [x] Bootstrap logic: compose from `_default_config()` + `_load_yaml()` + `_apply_env_overrides()`, then for each key, write to DB only if not already present in the batch-read set
    **Notes:** Implemented in `_bootstrap_and_load()` lines 243-256. Calls `self._compose()` which chains _default_config + _load_yaml + _apply_env_overrides. Then iterates _ALLOWED_CONFIG_KEYS, writes to DB only if key not in `existing_keys` set built from batch-read.
- [x] Cache load logic: after bootstrap writes, `db.meta.get_by_prefix("config_")` again (or reuse if no writes happened), parse values, populate `self._cache`
    **Notes:** Cache holds parsed Python types (bool, int, float, str). DB holds string representations. The parse step in cache load converts DB strings to typed values using the same parsing logic currently in `_load_db_config()`. This asymmetry is intentional: DB is a flat string KV store, cache is the typed runtime interface.
      Lines 258-263: second `get_by_prefix("config_")` call reads all keys back, parses via `_parse_db_value()` static method (lines 276-285). Cache holds typed Python values; DB holds strings.
- [x] Add `_cache: dict[str, Any]` instance attribute initialized as empty dict in `__init__`
    **Notes:** Line 101: `self._cache: dict[str, Any] = {}`. Also kept `self._config` temporarily (line 102) for backward compat until Phase 4 removes it.
- [x] Call `_bootstrap_and_load()` from `__init__` so cache is warm before first read
    **Notes:** Line 104: `self._bootstrap_and_load()` as last line of `__init__`.
- [x] Verify via `lint_project_backend(path="nomarr/services/infrastructure/config_svc.py")`
    **Notes:** lint_project_backend: 0 errors, 1 file checked, clean.

### Phase 2: Rewrite read path — cache-only

- [x] Rewrite `get(key, default)` to do simple flat lookup: `self._cache.get(key, default)` — no dotted-path splitting
    **Notes:** Confirmed zero callers use dotted paths (the `worker.poll_interval` example in the docstring is aspirational, not real). All config keys are flat strings. Remove the dotted-path split logic and the docstring example that references it.
      Rewrote `get()` (lines 120-131): flat `self._cache.get(key, default)`. Renamed param from `key_path` to `key`. Removed dotted-path split logic and the dead `worker.poll_interval` docstring example.
- [x] Rewrite `get_config()` to return `ConfigResult(config=dict(self._cache))` — shallow copy for backward compat
    **Notes:** Shallow copy is O(n) where n is ~20 keys — negligible cost. Copy prevents callers from mutating the cache directly. Lock must cover the copy operation (see Phase 5).
      Rewrote `get_config()` (lines 106-119): returns `ConfigResult(config=dict(self._cache))`. Kept backward-compat `self._config` bridge temporarily (Phase 4 removes). Shallow copy prevents caller mutation.
- [x] Verify via `lint_project_backend(path="nomarr/services/infrastructure/config_svc.py")`
    **Notes:** lint_project_backend: 0 errors, 1 file checked, clean.

### Phase 3: Implement write-through setter — replace set_config_value()

- [x] Rename `set_config_value()` to `set(key: str, value: Any) -> None` — single public write API, no dual methods
    **Notes:** `set()` validates key is in `_ALLOWED_CONFIG_KEYS`, updates `self._cache[key]` with the value AS-IS (already typed from caller), then writes `str(value)` to DB meta with `config_` prefix. Cache holds parsed types; DB holds strings. The parse step only happens on cache load from DB. On `set()`, the caller provides the typed value directly.
      Replaced `set_config_value()` with `set(key, value)` (lines 134-151). Validates key against `_ALLOWED_CONFIG_KEYS`. Updates cache with typed value, stringifies for DB. Added `_write_to_db()` (lines 153-162) with try/finally/close pattern.
- [x] Add `_write_to_db(key: str, value: str) -> None` private method that handles the throwaway `Database()` connection and `db.meta.set()` call — isolates DB write plumbing
    **Notes:** Implemented in same edit as P3-S1. `_write_to_db()` at lines 153-162: throwaway Database(), try/finally/close, logs exception on failure.
- [x] Update all callers of `set_config_value()` to use `set()` (search: `config_if.py`, any other caller)
    **Notes:** One caller found: config_if.py:87. Updated `config_service.set_config_value(key, value)` to `config_service.set(key, value)`. No other callers found in codebase.
- [x] Remove stale docstring about "reload/restart" — changes are now immediate
    **Notes:** Old `set_config_value` docstring (with "Changes take effect after reload() or application restart") was fully replaced by new `set()` docstring. No mention of reload/restart remains in the method.
- [x] Verify via `lint_project_backend(path="nomarr/services/infrastructure/config_svc.py")`
    **Notes:** lint_project_backend(config_svc.py): 0 errors, clean.
- [x] Verify via `lint_project_backend(path="nomarr/interfaces/api/web/config_if.py")`
    **Notes:** lint_project_backend(config_if.py): 0 errors, clean.

### Phase 4: Remove dead code and consolidate whitelists

- [x] Rename `_compose()` to `_build_bootstrap_config()` — bootstrap-only, called from `_bootstrap_and_load()`
    **Notes:** Merge helpers (`_default_config`, `_load_yaml`, `_deep_merge`, `_apply_env_overrides`) are retained. DB-read step previously in `_compose()` is removed since bootstrap handles DB seeding separately.
      Renamed `_compose()` to `_build_bootstrap_config()` (line 287). Removed DB-read step, `overrides` param, and `NOMARR_IGNORE_DB_CONFIG` check. Now only composes defaults + YAML + ENV. All callers updated.
- [x] Remove `force_reload` parameter from `get_config()` — cache is always live, no reload concept
    **Notes:** Removed `force_reload` param from `get_config()`. No external callers used it. Method now returns `ConfigResult(config=dict(self._cache))` unconditionally.
- [x] Remove the old `self._config: dict[str, Any] | None` field — replaced by `self._cache`
    **Notes:** Removed `self._config` from `__init__`. Also removed the backward-compat bridge in `get_config()` that referenced it. `self._cache` is the only cache field now.
- [x] Remove `_load_db_config()` — logic inlined in `_bootstrap_and_load()`
    **Notes:** Deleted entire `_load_db_config()` method (was ~57 lines). DB reading logic is now in `_bootstrap_and_load()` with shared connection. Parse logic extracted to `_parse_db_value()` static method.
- [x] Consolidate editable-keys: define `WEB_EDITABLE_KEYS` frozenset in `config_svc.py` (web-UI-safe subset), keep `_ALLOWED_CONFIG_KEYS` for DB/ENV override validation (superset)
    **Notes:** Added `WEB_EDITABLE_KEYS` frozenset at lines 62-80. Contains 14 web-editable keys (includes navidrome_path_prefix_map). `_ALLOWED_CONFIG_KEYS` (superset, 18 keys) retained for DB/ENV validation.
- [x] Update `config_if.py` POST endpoint to import and use `WEB_EDITABLE_KEYS` instead of inline set
    **Notes:** config_if.py POST endpoint now imports and checks `WEB_EDITABLE_KEYS` (line 49). Inline 13-key set removed.
- [x] Update `config_if.py` GET endpoint to import and use `WEB_EDITABLE_KEYS` instead of inline set
    **Notes:** GET endpoint simplified to just `config_service.get_config_for_web()` + `ConfigResponse.from_dto(result)`. Inline 13-key set and manual filtering removed — service owns the whitelist now.
- [x] Move GET endpoint filtering logic into `get_config_for_web()` in ConfigService — interface should not own the key whitelist
    **Notes:** `get_config_for_web()` (line 197) now filters `self._cache` by `WEB_EDITABLE_KEYS` directly. Interface delegates entirely to service.
- [x] Update `config_if.py` POST response to remove "Use 'Restart Server' for changes to take full effect"
    **Notes:** POST response changed from `"Config '{key}' updated. Use 'Restart Server' for changes to take full effect."` to `"Config '{key}' updated successfully."` (line 54).
- [x] Verify via `lint_project_backend(path="nomarr/services/infrastructure/config_svc.py")`
    **Notes:** lint_project_backend(config_svc.py): 0 errors, clean.
- [x] Verify via `lint_project_backend(path="nomarr/interfaces/api/web/config_if.py")`
    **Notes:** lint_project_backend(config_if.py): 0 errors, clean.

### Phase 5: Update app.py and add thread safety

- [x] Add `threading.Lock` to ConfigService for `_cache` access — `set()` acquires lock for cache write + DB write, `get()` acquires lock for read, `get_config()` acquires lock for the `dict()` copy
    **Notes:** Writes from FastAPI request threads, reads from workers + request handlers. Lock covers all `_cache` access points including the `dict(self._cache)` copy in `get_config()`. CPython GIL makes simple dict ops atomic, but explicit lock is cleaner, future-proof, and ensures the copy isn't torn by a concurrent `set()`.
- [x] Simplify `Application.__init__`: remove `self._config = config_service.get_config().config` snapshot — use `config_service.get()` for startup values
    **Notes:** Application attributes that STAY as snapshots (truly static, set once): `db_path`, `models_dir`, `library_root`, `api_host`, `api_port`, `namespace`, `version_tag_key`, `tagger_version`, `worker_poll_interval`, `library_scan_poll_interval`, `worker_enabled_default`, `admin_password_config`. These are infrastructure values that cannot change at runtime. The `self._config` dict itself is removed.
      Removed `self._config = config_service.get_config().config` from __init__. Now uses `config_service.get()` for static snapshots (db_path, models_dir, library_root, calibrate_heads, library_auto_tag, library_ignore_patterns, admin_password). Also fixed 3 remaining `self._config.get()` calls in start() → `self._config_service.get()` (navidrome_path_prefix_map, spotify_client_id, spotify_client_secret). Zero remaining bare `self._config` references.
- [x] Update `Application.start()` to pass ConfigService to services that read live config (NavidromeService already done, others in Part B)
    **Notes:** NavidromeService already injected with config_service (prior session). PlaylistImportService (spotify creds) and TaggingService (calibrate_heads) still use frozen dataclass configs — these are Plan B scope (frozen dataclass elimination). No other services in start() need ConfigService injection for Plan A.
- [x] Verify via `lint_project_backend(path="nomarr/app.py")`
    **Notes:** lint_project_backend(app.py): 0 errors, clean.
- [x] Run full `lint_project_backend()` — zero errors
    **Notes:** Full lint pass: ruff 0 errors, mypy 0 errors (3 modified files), import-linter 9/9 contracts kept. Zero violations across entire codebase.

## Completion Criteria

- Config bootstrap: file → ENV → DB (once at startup, single throwaway connection)
- Config reads: always from mutable cache (populated from DB)
- Config writes: cache mutation triggers DB write (immediate effect)
- No multi-source recomposition at runtime
- `_compose()` renamed to `_build_bootstrap_config()` (bootstrap-only)
- `_load_db_config()` removed (inlined into bootstrap)
- Single `set()` method replaces `set_config_value()`
- `WEB_EDITABLE_KEYS` consolidated, GET filtering moved to `get_config_for_web()`
- Thread-safe cache access (lock covers get, set, and get_config copy)
- Application attributes clearly documented as static snapshots vs live reads
- All files pass `lint_project_backend` with zero errors
- Web UI config changes take effect immediately (no restart message)

## References

- Sibling: TASK-config-refactor-B-live-consumers.md (frozen dataclass elimination, downstream service updates)
