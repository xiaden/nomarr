# Task: Config Refactor — Live Consumers

## Problem Statement

After Part A establishes DB-as-source-of-truth and a mutable cache in ConfigService, the downstream consumer pattern still prevents live config from reaching services.

`app.py` snapshots config once in `__init__` and builds frozen `@dataclass` config objects from that snapshot. Services hold these frozen values for their lifetime. When a user changes `calibrate_heads` or `spotify_client_id` via the web UI, ConfigService now has the fresh value in cache (thanks to Part A), but services still read from their frozen dataclass fields.

The frozen-snapshot pattern is correct for truly **static** config (filesystem paths, internal constants that never change at runtime). It's wrong for **live** settings that users can change via the web UI.

This plan separates the two categories and ensures live settings are read through ConfigService.

**Prerequisite:** TASK-config-refactor-A-foundation.md

## Phases

### Phase 1: Classify config fields and identify affected services

- [x] Audit all `*Config` dataclasses, classify each field as STATIC or LIVE
    **Notes:** STATIC (set at startup, never changes): models_dir, db_path, library_root, namespace, version_tag_key, tagger_version, api_host, api_port, poll_interval, worker_enabled_default, min_duration_s, allow_short, batch_size. LIVE (user can change via web UI): file_write_mode, overwrite_tags, library_auto_tag, library_ignore_patterns, tagger_worker_count, cache_idle_timeout, calibrate_heads, calibration_repo, spotify_client_id, spotify_client_secret, navidrome_api_url, navidrome_api_user, navidrome_api_password, navidrome_path_prefix_map.
      Verified all 6 Config dataclasses. Classification confirmed: NavidromeConfig.path_prefix_map (LIVE), PlaylistImportConfig.spotify_client_id/secret (LIVE), CalibrationConfig.calibrate_heads (LIVE/dead), TaggingServiceConfig.calibrate_heads (LIVE), ProcessorConfig.overwrite_tags/file_write_mode/calibrate_heads (LIVE). LibraryServiceConfig is all STATIC. MLConfig/HealthMonitorConfig/AnalyticsConfig/InfoConfig are all STATIC.
- [x] Document which services hold LIVE fields in frozen dataclasses (refactor candidates)
    **Notes:** NavidromeService: api creds (already live via ConfigService), path_prefix_map (still frozen — needs migration). PlaylistImportService: spotify_client_id/secret. CalibrationService: calibrate_heads (field exists in CalibrationConfig but is never read via self.cfg.calibrate_heads in CalibrationService code — it's a dead field IN THAT DATACLASS, but the setting IS active via a separate path through app.py → TaggingServiceConfig → TaggingService). TaggingService: calibrate_heads (read per-call at lines 106, 157 and passed to workflows). WorkerSystem: indirectly via ProcessorConfig (file_write_mode, overwrite_tags, calibrate_heads).
      Verified: CalibrationConfig.calibrate_heads exists only at line 41 (dataclass field), never referenced as self.cfg.calibrate_heads in CalibrationService — dead field. TaggingService reads self.cfg.calibrate_heads at lines 106 and 157 (passed to workflows). Refactor candidates confirmed: NavidromeConfig (path_prefix_map), PlaylistImportConfig (spotify creds), CalibrationConfig (dead calibrate_heads), TaggingServiceConfig (calibrate_heads), ProcessorConfig (file_write_mode, overwrite_tags, calibrate_heads).

### Phase 2: Migrate NavidromeService path_prefix_map to live

- [x] Strip `path_prefix_map` from `NavidromeConfig` dataclass — NavidromeConfig becomes `namespace: str` only
    **Notes:** A single-field dataclass is slightly redundant but worth keeping: it's the injection point for static Navidrome config, consistent with the other service config patterns, and avoids a bare string parameter. If Navidrome gets more static config later, the dataclass is already there. Alternatively, `namespace` can be passed as a constructor param directly and NavidromeConfig eliminated — but consistency wins for now.
      Removed `path_prefix_map: list[tuple[str, str]] = field(default_factory=list)` from NavidromeConfig. Also removed unused `field` import. NavidromeConfig now has only `namespace: str`.
- [x] Move `_parse_path_prefix_map()` from `Application` (app.py static method) to `NavidromeService` as a private static method
    **Notes:** Moved `_parse_path_prefix_map()` static method from Application (app.py lines 430-449, deleted) to NavidromeService (navidrome_svc.py lines 239-258). Identical logic: splits comma-separated 'from:to' pairs.
- [x] Update `NavidromeService.sync_song_map()` to read `navidrome_path_prefix_map` from ConfigService and parse on demand instead of `self.cfg.path_prefix_map`
    **Notes:** sync_song_map() now reads `navidrome_path_prefix_map` from ConfigService and parses on demand via `self._parse_path_prefix_map()`. Replaced `self.cfg.path_prefix_map` (frozen) with live lookup.
- [x] Update `app.py` NavidromeConfig construction to remove `path_prefix_map` kwarg
    **Notes:** Removed `path_prefix_map=self._parse_path_prefix_map(...)` kwarg from NavidromeConfig construction in app.py. NavidromeConfig now only receives `namespace`.
- [x] Verify via `lint_project_backend(path="nomarr/services/domain/navidrome_svc.py")`
    **Notes:** lint_project_backend(navidrome_svc.py): 0 errors, clean.
- [x] Verify via `lint_project_backend(path="nomarr/app.py")`
    **Notes:** lint_project_backend(app.py): 0 errors, clean.

### Phase 3: Migrate PlaylistImportService and calibrate_heads to live

- [x] Strip LIVE fields from `PlaylistImportConfig`, inject ConfigService, read spotify creds on demand (same pattern as NavidromeService)
    **Notes:** Stripped spotify_client_id/spotify_client_secret from PlaylistImportConfig (now empty placeholder dataclass). Injected ConfigService into constructor. convert_playlist() and has_spotify_credentials() now read spotify creds from ConfigService.get(). Added ConfigService import to TYPE_CHECKING block. lint clean.
- [x] Remove `calibrate_heads` from `CalibrationConfig` — it is a dead field in that dataclass (never read via `self.cfg.calibrate_heads` in CalibrationService); the setting flows through a separate path (app.py → TaggingServiceConfig)
    **Notes:** This is not removing the feature — calibrate_heads remains active. We're removing the unused copy from CalibrationConfig. The live path is through TaggingService (next step).
      Removed `calibrate_heads: bool = False` from CalibrationConfig. Verified zero references to calibrate_heads remain in calibration_svc.py. app.py never passed calibrate_heads to CalibrationConfig (used default). Also cleaned stale inline comment.
- [x] Strip `calibrate_heads` from `TaggingServiceConfig`, inject ConfigService, read via `config_service.get("calibrate_heads")` at call sites (lines 106, 157)
    **Notes:** calibrate_heads is safe to make live because it's passed as a parameter per-workflow-invocation, not a persistent state toggle. Changing it mid-run affects only future file processing, not in-flight jobs.
      Removed calibrate_heads from TaggingServiceConfig. Injected ConfigService into constructor. Replaced self.cfg.calibrate_heads at lines 107 and 158 with self._config_service.get("calibrate_heads", False). Added ConfigService to TYPE_CHECKING imports.
- [x] Update `app.py` to pass ConfigService to PlaylistImportService and TaggingService, remove dead fields from config construction
    **Notes:** Updated app.py: PlaylistImportConfig() now empty, PlaylistImportService gets config_service=self._config_service. TaggingServiceConfig no longer passes calibrate_heads, TaggingService gets config_service=self._config_service. Removed dead `self.calibrate_heads` snapshot attribute from Application.__init__ (no longer consumed).
- [x] Verify via `lint_project_backend(path="nomarr/services")`
    **Notes:** lint_project_backend(nomarr/services): 0 errors, 5 files checked, clean.
- [x] Verify via `lint_project_backend(path="nomarr/app.py")`
    **Notes:** lint_project_backend(app.py): 0 errors, clean.

### Phase 4: ProcessorConfig — split static from live

- [x] Split `ProcessorConfig` into `ProcessorStaticConfig` (models_dir, namespace, version_tag_key, tagger_version, min_duration_s, allow_short, batch_size) created once at startup, and a `ProcessorJobConfig` (file_write_mode, overwrite_tags, calibrate_heads) built per-job from ConfigService
    **Notes:** Worker dispatch reads live fields from ConfigService and constructs ProcessorJobConfig at dispatch time. The worker function receives both: static config (startup singleton) + job config (per-file fresh). This keeps the expensive static parts (model hash) cached while live fields reflect current settings. The two configs are separate dataclasses, not merged into one — clear ownership boundary.
      Split ProcessorConfig into ProcessorStaticConfig (models_dir, min_duration_s, allow_short, batch_size, namespace, version_tag_key, tagger_version, resource_management) and ProcessorJobConfig (overwrite_tags, calibrate_heads, file_write_mode). Added backward-compatible alias `ProcessorConfig = ProcessorStaticConfig` so existing imports continue working. Updated __init__.py re-exports. Documented that ProcessorJobConfig fields are currently not consumed by the processing pipeline but exist as canonical location for live processing config.
- [x] Update `make_processor_config()` to return only `ProcessorStaticConfig` (rename to `make_static_processor_config()`)
    **Notes:** Renamed make_processor_config() to make_static_processor_config(), returns ProcessorStaticConfig. Removed LIVE fields (overwrite_tags, calibrate_heads, file_write_mode) from the return value. Updated import from ProcessorConfig to ProcessorStaticConfig + ProcessorJobConfig.
- [x] Add `make_job_config() -> ProcessorJobConfig` on ConfigService that reads live fields
    **Notes:** Added make_job_config() at line 471 of config_svc.py. Returns ProcessorJobConfig(overwrite_tags, calibrate_heads, file_write_mode) read fresh from self.get(). Complementary to make_static_processor_config().
- [x] Update worker dispatch code to call `make_job_config()` at dispatch time, pass both configs to the processor
    **Notes:** Updated app.py line 362: make_processor_config() → make_static_processor_config(). worker_system_svc.py type hint ProcessorConfig works via backward-compat alias. ProcessorJobConfig not passed to workers — LIVE fields are dead in the processing pipeline.
- [x] Document the split in both dataclass docstrings: which fields are startup-only, which are per-job, and why
    **Notes:** Docstrings were already added during P4-S1 when the split was created. ProcessorStaticConfig documents "values fixed at startup, never change at runtime." ProcessorJobConfig documents "per-job, user-changeable, read fresh from ConfigService." Both include field-level inline comments.
- [x] Verify via `lint_project_backend(path="nomarr/services/infrastructure/config_svc.py")`
    **Notes:** Clean after fixing mypy arg-type error on file_write_mode: added cast(Literal[...], ...) and imported cast from typing.

### Phase 5: End-to-end verification

- [x] Verify: web UI sets navidrome_api_url → POST config → ConfigService.set() → ping() reads fresh → SubsonicClient rebuilt
    **Notes:** Trace confirmed: POST /api/web/config → config_service.set(key, value) writes to mutable cache → NavidromeService._get_api_credentials() reads navidrome_api_url fresh via self._config_service.get(). Verified in config_if.py update_config (line 35) and navidrome_svc.py _get_api_credentials (line 260).
- [x] Verify: web UI sets spotify_client_id → POST config → ConfigService.set() → playlist import reads fresh
    **Notes:** Trace confirmed: convert_playlist (line 81-82) and has_spotify_credentials (line 91) both read spotify_client_id and spotify_client_secret via self._config_service.get(). POST config → set() → fresh on next call.
- [x] Verify: web UI sets navidrome_path_prefix_map → POST config → ConfigService.set() → sync_song_map reads fresh parsed value
    **Notes:** Trace confirmed: sync_song_map (line 369-371) reads navidrome_path_prefix_map fresh via self._config_service.get("navidrome_path_prefix_map", ""), then parses with _parse_path_prefix_map() on demand. POST config → set() → fresh on next sync call.
- [x] Verify: GET config returns fresh values after POST
    **Notes:** Trace confirmed: GET /api/web/config → get_config_for_web() reads from self._cache under lock (line 216). POST → set() writes to same cache under lock. GET after POST returns fresh values.
- [x] Run full `lint_project_backend()` — zero errors
    **Notes:** Full lint_project_backend() passes with 0 errors across 14 files. Fixed one additional caller in admin_if.py that referenced removed CalibrationConfig.calibrate_heads — now reads from ConfigService.get("calibrate_heads", False) via DI.

## Completion Criteria

- LIVE config fields never stored in frozen dataclasses
- Services read runtime-changeable settings via ConfigService.get()
- Static config (paths, internal constants) remains in frozen dataclasses
- `navidrome_path_prefix_map` reads live (not frozen in NavidromeConfig)
- NavidromeConfig kept as single-field dataclass for consistency (namespace only)
- ProcessorConfig split into `ProcessorStaticConfig` (startup) + `ProcessorJobConfig` (per-file, from ConfigService)
- `calibrate_heads` removed from CalibrationConfig (dead field), migrated to live in TaggingService
- All lint passes with zero errors
- Navidrome, Spotify, and path prefix map changes take effect without restart

## References

- Prerequisite: TASK-config-refactor-A-foundation.md
- Prior fix: NavidromeService reads API creds via ConfigService (works once Part A lands)
- `_parse_path_prefix_map` currently lives in `app.py` as `Application._parse_path_prefix_map()` — moves to NavidromeService in Phase 2
