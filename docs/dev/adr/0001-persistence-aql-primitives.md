# ADR 0001: Persistence uses reusable AQL templates + capability bindings

## Status

Accepted

## Context

Nomarr persistence had grown a broad collection abstraction that duplicated behavior already provided by python-arango (generic CRUD roots, field accessors, query-spec/template scaffolding).

That drift increased API surface area without adding Nomarr-specific value.

## Decision

Persistence will center on:

1. python-arango client/database access in `nomarr/persistence/db.py`
2. small reusable AQL templates/primitives in `nomarr/persistence/aql/`
3. thin collection/domain capability bindings in `nomarr/persistence/database/`

Methods belong in Nomarr persistence only when they encode:

- reusable Nomarr AQL query capability, or
- explicit app query intent that cannot be cleanly expressed by existing reusable templates.

The default is **template reuse with safe binding** (collection binds, validated field binds, value binds), not handwritten per-collection AQL as a new baseline.

## Consequences

- New app-intent operations are added under `nomarr/persistence/database/*_aql.py` as thin bindings where possible.
- Shared AQL execution/query helpers are added under `nomarr/persistence/aql/`.
- Business logic remains outside persistence.
- Existing broad collection wrappers are compatibility-only while callers are migrated to explicit operation modules.
