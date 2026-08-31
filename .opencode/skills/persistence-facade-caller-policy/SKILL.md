---
name: persistence-facade-caller-policy
description: ADR-046 thin persistence intent-facade caller policy — who may call db.library/db.app/db.ml (components, services, workflows incl. service workers), who may not (interfaces, helpers), the thin-single-atomic-intent rule, and the exact enforcement surfaces (pyproject import-linter contracts, tests/test_architecture_qc.py, layer guidance files) that must stay in sync. Use when editing layer guidance, import-linter contracts, architecture QC tests, or deciding whether a service/workflow persistence call is legal.
---

# Persistence Facade Caller Policy (ADR-046)

## Mental Model

Nomarr persistence has one public boundary: the injected `Database` facade and its `db.library` / `db.app` / `db.ml` intent namespaces. ADR-046 (Accepted 2026-08-30) lets **components, services, and workflows** (including service-classified workers) call that facade directly, provided the call is **thin** — one atomic persistence intent or one thin recipe step. Interfaces and helpers remain persistence-free. Everything below the facade (Tier-1 `sql/`, Tier-2 `database/` repos, `mappers/`, `models/`, `pg_engine`, sessions, transactions) stays persistence-private. Semantic thinness (no sequencing of lower-level calls, no collection-level choreography, no business rules) cannot be statically enforced — it is a review discipline; side-effectful reads (hydration) are treated as commands during review.

## Coverage

**Documented:** ADR-046 caller matrix; all contradictory guidance locations (skills, docs, tests); the import-linter contracts and QC tests that enforce it; the one existing code violation.
**Not yet documented:** post-implementation drift (this skill should be refreshed after the operationalization lands).
**Last extended:** 2026-08-31

## Key Findings

### Enforcement surfaces (must change together)
- `pyproject.toml` L326-336 contract "Only components and services may import persistence" — re-scope `source_modules` to `["nomarr.interfaces", "nomarr.helpers"]`, drop the `nomarr.workflows.*.* -> nomarr.persistence.db` ignore (L334-336).
- `pyproject.toml` L338-348 "Services may only import Database for type hints" — rename to a Tier-2 ban; keep `forbidden_modules = ["nomarr.persistence.database"]`; drop type-hints-only comment.
- `pyproject.toml` L313-318 "Interfaces should be thin" — unchanged, preserves the interface prohibition.
- `tests/test_architecture_qc.py` L481-518 tier1/tier2 test — pattern only bans `nomarr.persistence.database`; `nomarr.persistence.sql` (Tier-1) is NOT covered, interfaces NOT scanned, docstring references superseded ADR-031 and mislabels Tier-1 as `database`.
- `tests/test_architecture_qc.py` has no test banning interfaces from persistence, and no test banning `mappers/`/`models/`/`api/`/`pg_engine` imports above persistence.

### Guidance that contradicts the policy (all say "never call persistence directly" or "type only")
- `.opencode/skills/nomarr-layers/SKILL.md` L98 checklist item
- `.opencode/skills/nomarr-layers/references/services.md` L95-99 Persistence Rule
- `.opencode/skills/nomarr-layers/references/workflows.md` L36-40 Persistence Rule
- `nomarr/services/SERVICES.md` L210 (type only) + L218 ("Calling db.* methods directly" forbidden)
- `nomarr/workflows/WORKFLOWS.md` L154 (type only) + L163/L214/L218 ("Only components may call db.*")
- `nomarr/components/COMPONENTS.md` L198 ("components are the only layer that may")
- `nomarr/persistence/__init__.py` docstring ("services, workflows must never access the database directly")
- `tests/sabotage/test_song_tag_facade_boundary.py` L20-22 docstring ("type-only from nomarr.persistence import Database")
- `nomarr/persistence/PERSISTENCE.md` L19 ("Components may call persistence directly" — should list all three layers)

### Consistent surfaces (do NOT change)
- `references/interfaces.md`, `references/persistence.md` (persistence.md already shows workflow calling db.library as correct), `docs/dev/architecture.md` (no explicit contradiction), ASR-0013/ASR-0014 (already name components/workflows/services), `test_higher_layers_do_not_import_persistence_collection_or_accessor_internals` + pyproject L350-358 (legacy ArangoDB-era tripwire; paths no longer exist, keep as resurrection guard).

### Existing code violation
- `nomarr/components/tagging/tag_query_comp.py:18` — top-level `from nomarr.persistence.mappers.tag_mapper import tags_from_tag_rows`. A new mapper ban fails here. `tags_from_tag_rows` is a pure row→`Tags` converter; the component builds `{name, value}` dicts itself, so it can construct `Tags` directly from domain dataclasses (`nomarr.helpers.dataclasses.tags_dataclass`) without importing the mapper.

### Live usage (ADR codifies existing callers)
- 30 service files + 34 workflow files import `nomarr.persistence.db` (mostly lazy); 79 `db.library`/`db.app`/`db.ml` call sites in services+workflows. Interfaces and helpers import zero persistence modules. `nomarr/app.py:180` imports `pg_engine` (composition root — outside layer policy, keep).

## Critical Invariants
- The facade is the **sole** public persistence boundary — never widen it to repos/mappers/models/sql.
- Interfaces and helpers stay persistence-free (import-linter + QC must keep that).
- Tier-1/Tier-2/collection bans are preserved while the caller set expands.
- Order matters when editing pyproject: re-scope the L326 contract before removing the workflows ignore, or 34 workflow runtime imports break the gate.
- Semantic thinness is review-enforced, not machine-enforced — do not claim a static test proves it.

## Sources
- artifacts/decisions/ADR-046-allow-thin-persistence-intent-facade-calls-from-services-and-workflows.md
- pyproject.toml [tool.importlinter.contracts] (L284-366)
- tests/test_architecture_qc.py; tests/unit/architecture/test_library_domain_boundary.py; tests/sabotage/*
- .opencode/skills/nomarr-layers/{SKILL.md,references/*.md}; nomarr/{services/SERVICES.md,workflows/WORKFLOWS.md,components/COMPONENTS.md,persistence/{PERSISTENCE.md,__init__.py}}
- ASR-0013, ASR-0014, ADR-042 (all in force, consistent)
