# Task: Migration System — Baseline + Delta Pattern

## Problem Statement

Nomarr's migration system has two sources of truth for schema state:
1. `ensure_schema()` in `arango_bootstrap_comp.py` — creates all collections, indexes, graphs on fresh install
2. Migration files (`V004`–`V019`) — apply incremental changes for existing installs

Both must be kept in sync manually. When they drift (as V19's `vector_promotion_locks` demonstrates — present in the migration but missing from `ensure_schema`), fresh installs get a different schema than migrated installs.

The fix: adopt a **baseline + delta** pattern:
- `ensure_schema()` = frozen baseline snapshot (the schema at the last consolidation point)
- Migrations = deltas from that baseline
- On consolidation (major release), current DB state becomes the new `ensure_schema`, old migrations are dropped, schema version resets
- **No dual-maintenance**: new schema changes go in a migration file ONLY, not in `ensure_schema`

## Phases

### Phase 1: Fix Current Drift
- [x] Add `vector_promotion_locks` document collection to `_create_collections` in `arango_bootstrap_comp.py`
- [x] Verify `ensure_schema` now matches the cumulative effect of V004–V019 migrations
    **Notes:** Cross-referenced V019 migration against ensure_schema. All collections, indexes, and graphs now match. vector_promotion_locks was the only missing piece.
- [x] Run `lint_project_backend` on `nomarr/components/platform`

### Phase 2: Update Migration Documentation
- [x] Rewrite `docs/dev/migrations.md` to document the baseline + delta pattern, clarifying that `ensure_schema` is a frozen baseline and new migrations are the ONLY place for schema changes
- [x] Update `CLAUDE.md` project structure comment (currently says `V004-V014`, should reflect current state and the new pattern)
- [x] Update `.github/copilot-instructions.md` Alpha Development Policy section to remove guidance about editing `ensure_schema` alongside migrations
- [x] Update `ensure_schema()` docstring to clarify it is a frozen baseline, not to be edited per-migration

### Phase 3: Update Consolidation Script
- [x] Update `scripts/consolidate_migrations.py` docstring and summary text to reflect the new baseline + delta pattern
- [x] Ensure the baseline migration template in the script still matches the current schema (add `vector_promotion_locks`)
- [x] Run `lint_project_backend` on the full workspace
    **Notes:** W293 in consolidate_migrations.py fixed. PERF401 in validate_skills.py is pre-existing and unrelated.

## Completion Criteria
- `ensure_schema` creates the exact same schema as running all V004–V019 migrations on a V003 baseline
- `vector_promotion_locks` collection is present in both `ensure_schema` and the consolidation script's baseline template
- All documentation consistently describes the baseline + delta pattern
- No documentation references the old "edit ensure_schema alongside each migration" workflow
- `lint_project_backend` passes with zero errors

## References
- `nomarr/components/platform/arango_bootstrap_comp.py` — ensure_schema and helpers
- `nomarr/migrations/V019_navidrome_graph_model.py` — the migration that drifted
- `docs/dev/migrations.md` — primary migration documentation
- `scripts/consolidate_migrations.py` — consolidation tooling
- `CLAUDE.md` and `.github/copilot-instructions.md` — AI instruction files
