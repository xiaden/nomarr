# Task: Config Schema Registry

## Problem Statement

Nomarr's configuration has 18 keys defined across 5 independent sources that have drifted apart:

- `_default_config()` — dict literal with defaults
- `_ALLOWED_CONFIG_KEYS` — manually maintained set
- `WEB_EDITABLE_KEYS` — manually maintained frozenset
- `_apply_env_overrides()` — hardcoded env-var-to-key mapping in docstring
- Frontend `CONFIG_METADATA` — duplicated labels/types in TypeScript

This causes: dead keys persisted to DB (`overwrite_tags` — removed from all consumers, still in defaults/allowed/web-editable), ghost keys in frontend (`calibration_repo`, `cache_idle_timeout` — in DB but no backend consumer reads them), a duplicate negative-int parser bug in `_apply_env_overrides` (fixed in `_parse_db_value` but not here), and frontend/backend metadata drift (10 keys in `CONFIG_METADATA` vs 14 in `WEB_EDITABLE_KEYS`).

The fix: a single co-located schema file that is the **sole source of truth** for all config keys, their types, defaults, and UI metadata. `ConfigService` derives its key sets and defaults from this schema via `dataclasses.fields()` introspection. The frontend either renders from schema served by the backend or stays in sync via a startup assertion.

### Design Decisions (agreed in prior discussion)

- **StaticConfig** — frozen dataclass for startup-only values (models_dir, db_path, library_root, admin_password). Set once via config file or ENV, never changed at runtime, never exposed to web UI.
- **DynamicConfig** — mutable dataclass for web-editable settings (calibrate_heads, tagger_worker_count, etc.). Read from DB cache, writable via web UI.
- **DYNAMIC_FIELD_META** — companion dict co-located in same file, keyed by field name, with label/description/ui_type for frontend rendering.
- **LibraryConfigFields** — TypedDict + `validate_library_config()` for per-library config (file_write_mode, future fields). Not a dataclass because it's a document sub-schema, not a standalone config object.
- **Derived key sets** — `_ALLOWED_CONFIG_KEYS` and `WEB_EDITABLE_KEYS` computed from dataclass fields, not manually maintained.
- **Startup assertion** — `DYNAMIC_FIELD_META` keys must equal `DynamicConfig` field names, enforced at import time.
- **Dead keys removed** — `overwrite_tags` (no consumer), `file_write_mode` as global key (per-library only via `LibraryDict`), `calibration_repo` and `cache_idle_timeout` (no backend consumer — remove from config entirely, can be re-added when wired).

## Phases

### Phase 1: Create Config Schema File

- [x] Create `nomarr/helpers/config_schema.py` with `StaticConfig` frozen dataclass (fields: models_dir, db_path, library_root, admin_password with typed defaults)
    **Notes:** Created nomarr/helpers/config_schema.py with StaticConfig frozen dataclass: models_dir="/app/models", db_path="/app/config/db/nomarr.db", library_root="/media", admin_password=None. lint_project_backend: 0 errors.
- [x] Add `DynamicConfig` mutable dataclass to same file (fields: calibrate_heads, tagger_worker_count, library_auto_tag, library_ignore_patterns, spotify_client_id, spotify_client_secret, navidrome_api_url, navidrome_api_user, navidrome_api_password, navidrome_path_prefix_map — with typed defaults matching current `_default_config()`)
    **Notes:** Added DynamicConfig mutable dataclass with 10 fields matching _default_config() defaults: calibrate_heads=False, tagger_worker_count=None, library_auto_tag=True, library_ignore_patterns="", spotify_client_id=None, spotify_client_secret=None, navidrome_api_url=None, navidrome_api_user=None, navidrome_api_password=None, navidrome_path_prefix_map="". lint: 0 errors.
- [x] Add `DYNAMIC_FIELD_META: dict[str, FieldMeta]` with label/description/ui_type for each DynamicConfig field, co-located in same file
    **Notes:** Added FieldMeta TypedDict and DYNAMIC_FIELD_META dict with 10 entries matching DynamicConfig fields. Labels/descriptions ported from frontend CONFIG_METADATA + navidrome ApiSettingsPanel. Removed from **future** import annotations (breaks TypedDict class syntax). Fixed Literal string quotes. lint: 0 errors.
- [x] Add `LibraryConfigFields` TypedDict with `file_write_mode: Literal["none", "minimal", "full"]` and a `validate_library_config()` function
    **Notes:** Added LibraryConfigFields TypedDict with file_write_mode: Literal["none", "minimal", "full"] and validate_library_config() function with frozenset validation. type: ignore[typeddict-item] on narrowed assignment (runtime-validated but mypy can't prove Literal narrowing from object). lint: 0 errors.
- [x] Add module-level assertion: `assert set(DYNAMIC_FIELD_META) == {f.name for f in dataclasses.fields(DynamicConfig)}` to prevent drift
    **Notes:** Added module-level assertion at line 128: assert set(DYNAMIC_FIELD_META) == {f.name for f in dataclasses.fields(DynamicConfig)}. Includes diagnostic message showing extra/missing keys on failure. Verified import succeeds (assertion passes). lint: 0 errors.
- [x] Add derived constants: `STATIC_KEYS`, `DYNAMIC_KEYS`, `ALL_CONFIG_KEYS`, `WEB_EDITABLE_KEYS` computed from dataclass fields
    **Notes:** Added STATIC_KEYS (4), DYNAMIC_KEYS (10), ALL_CONFIG_KEYS (14), WEB_EDITABLE_KEYS (=DYNAMIC_KEYS) as frozensets derived from dataclasses.fields(). Verified via import: 4 static keys, 10 dynamic keys, 14 total. Dead keys correctly absent. lint: 0 errors.

### Phase 2: Refactor ConfigService to Use Schema

- [x] Replace `_default_config()` method body with construction from `StaticConfig` and `DynamicConfig` field defaults via `dataclasses.fields()` + `dataclasses.asdict()`
    **Notes:** Replaced _default_config() body (lines 343-356) with dataclasses.asdict(StaticConfig()) + dataclasses.asdict(DynamicConfig()). Added import of dataclasses, StaticConfig, DynamicConfig, ALL_CONFIG_KEYS, WEB_EDITABLE_KEYS from config_schema. Lint shows expected F811/no-redef for WEB_EDITABLE_KEYS (old manual definition still present — removed in P2-S2).
- [x] Remove manual `_ALLOWED_CONFIG_KEYS` set and `WEB_EDITABLE_KEYS` frozenset from config_svc.py — import derived versions from config_schema
    **Notes:** Removed manual WEB_EDITABLE_KEYS frozenset (14 keys) and _ALLOWED_CONFIG_KEYS set (18 keys). Replaced with_ALLOWED_CONFIG_KEYS = ALL_CONFIG_KEYS (imported from config_schema). WEB_EDITABLE_KEYS also imported from config_schema. 44 lines of manual key lists replaced with 3-line derived assignment. lint: 0 errors.
- [x] Refactor `_apply_env_overrides()` to iterate `dataclasses.fields()` on both dataclasses with unified type-aware parsing (reuse `_parse_db_value` logic), fixing the negative-int parser bug
    **Notes:** Replaced _apply_env_overrides() body: removed inline parser (buggy with negative ints) and replaced with self._parse_db_value(env_value) call. Removed stale docstring listing 12 hardcoded env vars. Now uses_ALLOWED_CONFIG_KEYS (derived from schema) for the whitelist. Fixed f-string to %-format for logger. lint: 0 errors.
- [x] Update `config_if.py` import to use `WEB_EDITABLE_KEYS` from `nomarr.helpers.config_schema` instead of `nomarr.services.infrastructure.config_svc`
    **Notes:** Changed config_if.py line 12: import WEB_EDITABLE_KEYS from nomarr.helpers.config_schema instead of nomarr.services.infrastructure.config_svc. This is a proper downward import (interfaces → helpers) instead of lateral (interfaces → services). lint: 0 errors.

### Phase 3: Remove Dead Keys

- [x] Remove `overwrite_tags` from schema (do NOT add to either dataclass), remove from `_apply_env_overrides` docstring, remove from `build_resources/config/config.yaml`
    **Notes:** overwrite_tags was already absent from both dataclasses. Removed from build_resources/config/config.yaml (line 32). Cleaned docstring references in config_svc.py (line 104) and processing_dto.py (line 66). Updated config.yaml header comment. Verified via search_for_pattern: no remaining code references. lint: 0 errors.
- [x] Remove `file_write_mode` as a global config key (it lives on `LibraryDict.file_write_mode` per-library only — do NOT add to DynamicConfig); remove from `_apply_env_overrides` docstring and `config.yaml` global section
    **Notes:** Removed entire "Tag Writing Behavior" section (file_write_mode + comments) from config.yaml. Updated config.yaml header to reference per-library setting. Cleaned processing_dto.py docstring. Lint clean.
- [x] Remove `cache_idle_timeout` and `calibration_repo` from schema (no backend consumer reads them); remove from `_apply_env_overrides` docstring and `config.yaml`
    **Notes:** These can be re-added to DynamicConfig when a component actually consumes them. The schema makes re-addition trivial.
      Removed cache_idle_timeout (Model Cache section) and calibration_repo from config.yaml. Updated header comments. ConfigService already has no references to these keys.

### Phase 4: Frontend Alignment

- [x] Remove `overwrite_tags`, `cache_idle_timeout`, and `calibration_repo` entries from frontend `CONFIG_METADATA` in ConfigField.tsx
    **Notes:** Removed overwrite_tags, cache_idle_timeout, and calibration_repo entries from CONFIG_METADATA in ConfigField.tsx.
- [x] Remove `file_write_mode` from `CONFIG_METADATA` (it's per-library, not global config)
    **Notes:** Removed file_write_mode entry from CONFIG_METADATA. Kept select type support in component (Select/MenuItem imports + rendering logic) for future use.
- [x] Verify remaining `CONFIG_METADATA` keys match `DynamicConfig` fields exactly; add any missing keys (navidrome_path_prefix_map has no frontend UI — either add metadata or accept it's API-only)
    **Notes:** CONFIG_METADATA has 6 keys matching DynamicConfig. 3 navidrome keys handled by ApiSettingsPanel. navidrome_path_prefix_map accepted as API-only (path mapping, no UI needed). All 10 DynamicConfig fields accounted for.
- [x] Run frontend lint + build to verify no TypeScript errors
    **Notes:** ESLint + TypeScript both clean.

### Phase 5: Validation

- [x] Run `lint_project_backend` on full workspace — zero errors
    **Notes:** lint_project_backend check_all=True: zero errors.
- [x] Run `lint-imports` to verify no layer violations (config_schema is in helpers, imported by services and interfaces)
    **Notes:** lint-imports: 9 contracts kept, 0 broken. config_schema in helpers is correctly importable by services and interfaces.
- [x] Verify startup assertion passes by checking schema file parses cleanly
    **Notes:** Module imports cleanly. Drift assertion passes. Counts: 4 static + 10 dynamic = 14 total. WEB_EDITABLE_KEYS = 10.
- [x] Verify `build_resources/config/config.yaml` matches schema (only keys present in StaticConfig + DynamicConfig)
    **Notes:** config.yaml has exactly 14 keys matching ALL_CONFIG_KEYS. Zero extra, zero missing. Perfect 1:1 alignment.

## Completion Criteria

- Single source of truth: all config keys, defaults, and types defined in `nomarr/helpers/config_schema.py`
- No manual key lists in ConfigService — `_ALLOWED_CONFIG_KEYS` and `WEB_EDITABLE_KEYS` are derived
- Zero dead keys: `overwrite_tags`, global `file_write_mode`, `cache_idle_timeout`, `calibration_repo` removed from config pipeline
- `_apply_env_overrides` negative-int parser bug fixed
- Frontend `CONFIG_METADATA` keys are subset of `DynamicConfig` fields (no phantom keys)
- `lint_project_backend`, `lint-imports`, and frontend build all pass

## References

- Predecessor: plans/completed/TASK-config-refactor-A-foundation.md (DB as source of truth)
- Predecessor: plans/completed/TASK-config-refactor-B-live-consumers.md (live consumer migration)
- Config audit findings from prior conversation (dead keys, ghost keys, parser bug, frontend drift)
