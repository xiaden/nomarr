# ADR-016: Skip ensure_schema on Existing Databases

**Status:** Accepted  
**Date:** 2026-04-05  
**Tags:** migrations, persistence, arangodb, startup  
**Source Log:** director#L1  

## Context

`ensure_schema` (the frozen baseline bootstrap) ran on every application startup, idempotently recreating collections, indexes, and graphs. This caused migrations that drop or modify indexes to be silently undone on the next restart — `ensure_schema` would recreate the exact indexes the migration had removed. This produced a recurring crash loop in V021, which drops `library_id`-based unique indexes before nullifying the `library_id` field. On restart, `ensure_schema` rebuilt those indexes on data with null `library_id` values, causing unique constraint violations. Three fix attempts were needed before identifying `ensure_schema` as the root cause.

## Decision

`prepare_database_workflow` now checks if the database already has a version in the `meta` collection before calling `ensure_schema`. If a version exists (existing database), `ensure_schema` is skipped entirely and only pending migrations run. `ensure_schema` only executes on fresh databases with no prior schema version. This makes `ensure_schema` truly a one-time bootstrap, not a startup ritual.

## Consequences

- Migrations can safely drop/modify indexes and schema elements without `ensure_schema` recreating them on next restart
- Fresh installs still get the full baseline schema before any migrations run
- `ensure_schema` remains frozen — no need to keep it in sync with migration changes
- Any new schema elements for existing databases MUST be added via migrations, not by editing `ensure_schema`
- If a migration fails mid-way, the partial state persists — `ensure_schema` will NOT repair it on retry. Migrations must be written to be idempotent/resumable.
