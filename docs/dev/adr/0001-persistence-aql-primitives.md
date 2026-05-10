# ADR 0001: Persistence uses AQL primitives + explicit operations

## Status

Accepted

## Context

Nomarr persistence had grown a broad collection abstraction that duplicated behavior already provided by python-arango (generic CRUD roots, field accessors, query-spec/template scaffolding).

That drift increased API surface area without adding Nomarr-specific value.

## Decision

Persistence will center on:

1. python-arango client/database access in `nomarr/persistence/db.py`
2. small reusable AQL primitives in `nomarr/persistence/aql/`
3. explicit, reviewed domain operations in `nomarr/persistence/database/`

Methods belong in Nomarr persistence only when they encode reusable Nomarr AQL capability or explicit app query intent.

## Consequences

- New app-intent operations are added under `nomarr/persistence/database/*_aql.py`.
- Shared AQL execution/query helpers are added under `nomarr/persistence/aql/`.
- Business logic remains outside persistence.
- Existing broad collection wrappers are compatibility-only while callers are migrated to explicit operation modules.
