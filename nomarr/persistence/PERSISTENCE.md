# Persistence Layer

The persistence layer owns ArangoDB access for Nomarr.

## Target model

Persistence should default to:

1. python-arango connection access via `db.py`
2. reusable AQL templates/primitives in `aql/`
3. thin capability bindings in `database/` that bind collection names, allowed fields, and common query shapes

This approach balances two extremes:

- **not** a generic ORM/query-builder framework
- **not** handwritten per-collection AQL for every basic query shape

## Preferred extension path

```text
components/services
  -> db.<domain>_aql.<named_operation>(...)
  -> aql/primitives.py reusable template
  -> safe bind vars (@@collection, validated field names, value binds)
  -> ArangoDB
```

Use handwritten custom AQL in `database/*_aql.py` only when a reusable template cannot express the query cleanly and the operation is truly domain-specific.

## Legacy framework status

`collections.py`, `collections_base.py`, `accessors.py`, and related query-spec/template framework files remain as **legacy compatibility-only** internals while migration continues.

- Do not add new app-facing persistence features to the legacy framework.
- New persistence work should prefer reusable `aql/` templates and thin `database/` bindings.

## Current migration evidence

- Reusable primitives in `aql/primitives.py` include generic patterns such as:
  - field-filtered reads
  - filtered document listing
  - projected field listing
  - distinct edge-source counting through filtered vertices
  - keyed updates/inserts
- Capability bindings in `database/`:
  - `library_files_aql.py`
  - `libraries_aql.py`
- Migrated callers:
  - `components/library/library_file_query_comp.py` (selected query paths)
  - `components/library/library_records_comp.py` (library record CRUD/query paths)

## Migration strategy for legacy callers

- When touching a caller that still uses legacy collection/accessor/query-spec APIs, migrate that touched path to `database/*_aql.py` capability bindings backed by `aql/primitives.py`.
- Prefer extracting a reusable primitive first; only keep bespoke query text in `database/*_aql.py` when the shape is truly domain-specific.
- Remaining untouched legacy callers are allowed temporarily for incremental migration, but new persistence features should not be added to legacy surfaces.

## Rules

- Persistence may not import interfaces/services/workflows/components.
- Preserve Arango `_id` and `_key`.
- Keep business logic and orchestration outside persistence.
