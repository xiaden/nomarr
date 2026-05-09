# Collection-First Query-Spec Persistence — Implementation Parts

Design doc: `artifacts/designs/pending/DD-collection-first-query-spec-persistence.md`

---

## Parts

| Part | Title | Depends On | Layers | Session Scope |
|------|-------|-----------|--------|---------------|
| A | Query-spec foundation and AQL validation | None | persistence, tests | ~10 steps |
| B | Collection-first generic surface and compatibility shims | A | persistence | ~12 steps |
| C | Reclassify special capabilities and move orchestration up-layer | B | persistence, components/workflows | ~12 steps |
| D | Caller migration, cleanup, and enforcement | B, C | persistence, tests | ~12 steps |

---

## Dependency Graph

```text
A (query_specs, query_templates, aql_validation, tests)
│
└──► B (collection-first API on db/collections/accessors/base)
          │
          ├──► C (special capability audit + orchestration migration)
          │
          └──► D (caller migration, cleanup, enforcement, docs/tests)
```

---

## Execution Rounds

**Round 1:** A (no deps)
**Round 2:** B (depends on A)
**Round 3:** C (depends on B)
**Round 4:** D (depends on B and C)

---

## Per-Part Scope

### Part A: Query-spec foundation and AQL validation

Create the new architectural foundation for generic persistence operations:

- `nomarr/persistence/query_specs.py` — capability-family metadata, allowed criteria/operator forms, and collection/field metadata interpretation for generic collection-first operations.
- `nomarr/persistence/query_templates.py` — fixed first-party AQL templates for generic persistence capability families; no free-form template DSL.
- `nomarr/persistence/aql_validation.py` — spec/template validation, bind-time validation, and parse/explain hooks for test/CI use.
- Tests for validation and representative compile/parse coverage.

This part is intentionally additive. It should not yet force broad caller migration. Downstream contracts: the canonical capability taxonomy, naming grammar enforcement points, and validation API used by later parts.

### Part B: Collection-first generic surface and compatibility shims

Refactor the persistence surface so generic operations are collection-first and backed by the Part A foundation:

- update `nomarr/persistence/accessors.py`, `collections_base.py`, `collections.py`, and `db.py` as needed so collection-level generic operations are the normative path.
- keep field accessors only as compatibility shims; no new field-first capability surface.
- ensure naming grammar compliance for generic operations and keep fields as metadata/criteria rather than architectural namespaces.

This part establishes the new normative API shape while preserving runtime compatibility where necessary. Downstream contracts: stable collection-first generic operations and explicit compatibility boundaries for any remaining field-accessor aliases.

### Part C: Reclassify special capabilities and move orchestration up-layer

Audit current special helpers and keep only true storage-native primitives in persistence:

- preserve or normalize only justified storage-native operations such as graph traversal/cascade, ANN search, and any explicitly re-justified relationship/state primitive.
- reclassify vector-branded or transition-adjacent helpers that are really generic document operations or orchestration.
- move orchestration-heavy helpers to components/workflows where appropriate.
- explicitly resolve whether `transition` remains a dedicated persistence primitive or is replaced by a more general relationship/state mutation family.

This part is where old helper names go to either earn their keep or get evicted. Downstream contracts: final classification of persistence-native vs higher-layer responsibilities.

### Part D: Caller migration, cleanup, and enforcement

Finish the migration and enforce the new architecture:

- migrate remaining internal persistence code and nearby callers/tests to the collection-first surface.
- remove or further narrow obsolete helper names and compatibility-only internals where safe.
- add enforcement/tests to prevent new field-first APIs, naming-grammar drift, and unvalidated AQL template usage.
- update docs or ADR follow-up notes if implementation evidence requires a formal narrowing of field-accessor expectations.

This part should leave the persistence layer aligned with the DD’s exit criteria rather than merely introducing parallel mechanisms.


**Current status:** Parts A through D are complete. Part D caller migration cleanup, enforcement, retained seam notes, and final verification results are recorded in `CONTRACTS.md`.