# ADR-044: Nomarr Never Persists Navidrome Data Locally

**Status:** Accepted  
**Date:** 2026-08-18  
**Tags:** navidrome, persistence, architecture, plugin-boundary  
**Source Log:** exec-manager#L273  

## Context

Navidrome integration in Nomarr evolved through two conflicting directions. The sync-first work (TASK-sync-first-persistence-I2-navidrome-interfaces, PERSIST01 legacy-deletion series) established that Navidrome song/play data should flow through the plugin/request boundary: the Navidrome plugin crawls the Navidrome library, resolves Nomarr descriptors, and submits play history via API requests (e.g. the personal-playlists `top_plays` payload). Commit 4cda413a ("major AI rework") reintroduced/retained a full PostgreSQL persistence path for Navidrome data — `navidrome_tracks`, `navidrome_track_maps`, `navidrome_plays`, `navidrome_play_maps` tables, a `NavidromeRepo`, `AppDb` Navidrome methods, an `AppLegacyNavidromeDb` facade, graph persistence helpers, and a `sync_navidrome` workflow — contradicting the documented direction. The sync-song endpoint had already been disabled (410 Gone) because the backend-owned song-map sync was obsolete. Keeping two conflicting ownership models (backend-persisted Navidrome IDs vs plugin-boundary descriptors) created dead code, duplicate DTOs, and drift.

## Decision

Nomarr never persists Navidrome data in its own database. All Navidrome play/track data flows through the plugin/request boundary only: the Navidrome plugin (navidrome-plugin/) owns song↔Navidrome-ID resolution and playcounts; the backend receives play history as request payloads (e.g. `top_plays` in personal-playlists requests) and uses it transiently for taste-profile computation. Concretely: no navidrome tables exist in the schema (alembic 002_drop_navidrome_tables removes them), no NavidromeRepo/AppDb Navidrome methods/ORM models/repo DTOs exist, the legacy sync-song endpoint returns 410 Gone, and taste_profile_comp never falls back to DB-stored plays. The backend works with descriptor IDs, not stored Navidrome IDs.

## Consequences

Positive: single ownership model — Navidrome data lives on the Navidrome side and in the plugin; no dual bookkeeping, no stale mapping tables, no compatibility debt; taste profiles are deterministic functions of caller-provided play data. Negative: the backend cannot answer questions about Navidrome play history offline (any such feature must query the plugin/Navidrome or be fed via request data); any future feature needing Navidrome playcounts must accept them at the request boundary. Regression risk: a future rework must not re-add persistence tables — the sync-song endpoint and this ADR are the guardrails.

## References

commit 4cda413a (regression source); ADR-034 (taste profile); ADR-040 (persistence simplification); TASK-sync-first-persistence-I2-navidrome-interfaces; nomarr/persistence/PERSISTENCE.md
