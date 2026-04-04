# Task: Frontend Playlist Config Cleanup

## Problem Statement

Per-user playlist preferences (`pp_enabled`, type checkboxes, max/min songs) have moved to the Navidrome plugin config (Plan B). The Nomarr settings UI still shows these fields, creating confusion about where playlist configuration lives. This plan removes the migrated user-facing fields from the frontend, keeps the server-side algorithm tuning params (`half_life_days`, `top_n`, `min_play_count`, backbone, overwrite toggle), and relabels the section as "Playlist Algorithm Tuning."

No backend changes — config keys remain in ConfigService as server-side defaults.

**Prerequisite:** TASK-per-user-playlists-A-api-passthrough

## Phases

### Phase 1: Remove migrated config entries

- [x] In `frontend/src/features/config/components/ConfigField.tsx`, delete the `CONFIG_METADATA` entries for removed keys: `pp_enabled`, `pp_type_familiar`, `pp_type_discovery`, `pp_type_hidden_gems`, `pp_type_genre`, `pp_type_universal`, `pp_max_songs`, `pp_min_songs`
- [x] In `frontend/src/features/config/components/ConfigField.tsx`, update labels/descriptions on kept entries to reflect algorithm-tuning framing (e.g., `pp_half_life_days` description becomes "Exponential decay rate for play-history weighting (server default)")
- [x] In `frontend/src/features/config/components/ConfigSettings.tsx`, update `PP_ORDER` array to remove all deleted keys, keeping only: `pp_backbone_id`, `pp_overwrite_playlists`, `pp_top_n`, `pp_min_play_count`, `pp_half_life_days`
- [x] In `frontend/src/features/config/components/ConfigSettings.tsx`, delete the `PP_TYPE_KEYS` set entirely — no more checkbox group needed

### Phase 2: Simplify rendering and verify

- [x] In `ConfigSettings.tsx`, rename the section heading from "Personal Playlists" to "Playlist Algorithm Tuning", remove the `ppTypes`/`ppOther` split and the special `pp_enabled` rendering, remove the "Playlist Types" checkbox group block, render all remaining playlist entries in a single flat Stack
    **Result:** Renamed heading to "Playlist Algorithm Tuning", removed ppTypes/ppOther/pp_enabled special rendering and "Playlist Types" checkbox group, replaced with a single flat Stack over personalPlaylist
- [x] Remove the `ppTypes` and `ppOther` local variables derived from `PP_TYPE_KEYS` since the set no longer exists
    **Result:** Removed the 3-line ppTypes/ppOther block and the 9-line PP_TYPE_KEYS Set declaration, eliminating all references to the deleted set
- [x] If the `checkbox` field type variant in `ConfigField.tsx` is now dead code (no remaining keys use `type: "checkbox"`), remove that branch to avoid dead code
    **Result:** Removed the checkbox branch from ConfigField.tsx and cleaned up unused imports: Checkbox, FormControlLabel, and Tooltip — all were exclusively used by that branch
  **Notes:** Can be re-added later if future fields need checkboxes. YAGNI for now.
- [x] Verify `lint_project_frontend()` passes with zero errors and `npm run build` in `frontend/` succeeds
    **Result:** lint_project_frontend returned status clean (ESLint + TypeScript). npm run build completed in 912ms with no errors, 38 output chunks.

## Completion Criteria

- Frontend lint and build pass with zero errors
- Settings page shows "Playlist Algorithm Tuning" section with only: Backbone dropdown, Overwrite Playlists toggle, Top Plays to Fetch, Min Play Count, Recency Half-Life
- No `pp_enabled`, no playlist type checkboxes, no max/min songs fields visible
- General config section is unaffected
- No backend changes

## References

- Design doc: `plans/dev/design-per-user-playlists.md`
- Plan A: `plans/TASK-per-user-playlists-A-api-passthrough.md`
- Parts README: `plans/dev/per-user-playlists-parts/README.md`
- Contracts ledger: `plans/dev/per-user-playlists-parts/CONTRACTS.md`
