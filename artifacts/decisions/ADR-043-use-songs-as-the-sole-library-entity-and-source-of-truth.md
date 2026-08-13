# ADR-043: Use songs as the sole library entity and source of truth

**Status:** Accepted  
**Date:** 2026-08-07  
**Tags:** persistence, domain-model, schema, songs, hard-cut  
**Source Log:** nyx#L5  

## Context

Nomarr's first-establishment Alembic baseline creates a `songs` table, but the ORM, repositories, tag edges, processing-state models, facades, components, services, workflows, and tests still use the obsolete `library_files`/file-domain vocabulary. The application has never successfully established and run against the hard-cut database, so there are no supported existing databases or upgrade consumers to preserve. A song is the application entity; its source audio path is a detail of that song. Tag semantics and processing behavior are established independently and must not be redesigned by this decision.

## Decision

Make `songs` the sole canonical library entity in the initial database schema and all active application code. Correct the initial Alembic establishment source and all ORM models, repositories, tag/state relationships, facades, DTOs, components, services, workflows, tests, and documentation in one hard-cut repair. Remove `library_files`, `LibraryFile`, `LibraryFilesDb`, generic file-domain persistence APIs, and compatibility aliases from active runtime code. Filesystem helpers may retain file/path terminology only when operating on physical paths. Do not add an Alembic upgrade migration, dual schema, compatibility layer, or deprecation window. Preserve existing tag namespace, curation, confidence, gating, and writeback semantics.

## Consequences

The application vocabulary aligns with the user experience: a library contains songs, and songs carry source paths and derived data. The repair is breaking by design but has no supported database compatibility burden. Repository and facade APIs must be renamed and callers updated together. Initial-schema establishment and fresh-database integration tests become mandatory gates. Historical migration/ADR text may mention `library_files` only to explain the correction; active runtime code must not. Any future physical-file concerns remain infrastructure concerns rather than domain entities.

## Non-Goals

This decision does not redesign tag semantics, ML tier/gating math, calibration, vector storage, scan lifecycle, or frontend route structure. It does not introduce a new domain-dataclass framework or preserve unsupported database instances.

## References

artifacts/designs/pending/DD-song-domain-repair.md; artifacts/decisions/ADR-040-postgresql-pgvector-hard-cut-replacement-of-arangodb.md; artifacts/decisions/ADR-041-domain-model-dataclasses-natural-keys.md; artifacts/decisions/ADR-009-nom-tag-prefix-exclusion-from-user-editing.md; alembic/versions/001_initial_v1_baseline_schema.py
