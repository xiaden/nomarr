# Task: Personal Playlist F — Config + Frontend UI

## Problem Statement

The playlist generation pipeline (Plan E) requires configuration values to fill its `PlaylistConfig` TypedDict. These values need to be user-editable via the global config page, following the existing `DynamicConfig` + `DYNAMIC_FIELD_META` pattern. The frontend config page needs a "Personal Playlists" section to group these fields visually.

**Prerequisites:** Plan E (defines `PlaylistConfig` shape that config must fill)

## Phases

### Phase 1: Backend Config Schema

- [x] Add 13 fields to `DynamicConfig` in `nomarr/helpers/config_schema.py`: `pp_enabled: bool = False`, `pp_backbone_id: str = "effnet-discogs"`, `pp_half_life_days: float = 30.0`, `pp_top_n: int = 200`, `pp_min_play_count: int = 3`, `pp_max_songs: int = 50`, `pp_min_songs: int = 10`, `pp_overwrite_playlists: bool = True`, and 5 per-type toggles (`pp_type_familiar: bool = True`, `pp_type_discovery: bool = True`, `pp_type_hidden_gems: bool = True`, `pp_type_genre: bool = True`, `pp_type_universal: bool = True`).
- [x] Add matching `DYNAMIC_FIELD_META` entries for all 13 fields. Use `ui_type: "boolean"` for all bools, `ui_type: "number"` for ints/float, `ui_type: "text"` for `pp_backbone_id`. Labels: "Enabled", "Backbone ID", "Recency Half-Life (days)", "Top Plays to Fetch", "Min Play Count", "Max Songs per Playlist", "Min Songs per Playlist", "Overwrite Playlists", "Familiar Type", "Discovery Type", "Hidden Gems Type", "Genre Type", "Universal Type".
- [x] Verify `lint_project_backend` passes on `nomarr/helpers` with zero errors. The drift guard at import time will catch any DynamicConfig/DYNAMIC_FIELD_META mismatch.

### Phase 2: Frontend Config UI

- [x] Add section grouping to `ConfigSettings.tsx`. Group config keys by prefix: keys starting with `pp_` render under a "Personal Playlists" section header, remaining keys stay under a "General" section. Use MUI `Typography` + `Divider` for section headers. Partition `Object.entries(config)` by prefix.
- [x] Add `CONFIG_METADATA` entries in `ConfigField.tsx` for all 13 `pp_*` keys with labels (without prefix since sectioned), descriptions, and correct type values. If `number` type is not in the type union, add it and render with `type="number"` on the `TextField` for better UX.
- [x] Verify `lint_project_frontend()` passes with zero errors.

## Completion Criteria

- All 13 `pp_*` config fields exist in `DynamicConfig` with correct defaults
- `DYNAMIC_FIELD_META` drift guard passes (import-time assertion)
- Config fields are automatically web-editable via existing `WEB_EDITABLE_KEYS` mechanism
- Frontend config page shows "Personal Playlists" section with all 13 fields grouped
- `ConfigService.get("pp_enabled", False)` works for service-layer reads
- `lint_project_backend()` and `lint_project_frontend()` — zero errors
