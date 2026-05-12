# ADR-031: AQL Primitives and Intent Sub-Facades as Canonical Persistence Architecture

**Status:** Accepted  
**Date:** 2026-05-11  
**Tags:** persistence, architecture, aql, database  
**Supersedes:** ADR-025-schema-driven-persistence-constructor-supersedes-hand-written-aql-conventions, ADR-030-adopt-descriptor-based-database-facade-for-persistence-access  

## Context

The persistence layer grew into a custom ORM that reimplements behavior already provided by python-arango. It exposes multiple overlapping interaction models — field-scoped accessors (`db.library_files.path.get(...)`), collection-scoped verbs (`db.library_files.get(is_valid=True)`), query-spec templates, and raw escape hatches — spread across `collections.py`, `collections_base.py`, `accessors.py`, `constructor/`, `query_specs.py`, and `query_templates.py`.

This caused persistence mechanics to leak into components: to read a library, a component had to know whether to use `_id` vs `_key` access, cast results, and apply `Field()` criteria objects. The framework surface (field registration, verb dispatch, cascade compilation) was disproportionate to the value it added.

ADR-025 tried to address this with schema-driven constructors but added a third layer on top of the existing framework rather than replacing it. ADR-030 established the `Database` facade as the sole caller surface, which was directionally correct but applied over the wrong underlying shape.

PR 141 and PR 142 demonstrated a working fix for the library domain: reusable AQL template functions plus thin domain capability bindings, all hidden behind intent-named `Database` methods. This ADR formalizes that pattern as the canonical persistence architecture across the full layer.

## Decision

Persistence uses a three-tier model:

**Tier 1 — AQL Primitives** (`nomarr/persistence/aql/primitives.py`): Pure functions that take a `SafeDatabase` and return plain Python values. Each encodes one reusable, collection-agnostic AQL query shape. All dynamic field names are validated; all values use bind vars. No string-interpolated AQL.

**Tier 2 — Domain Capability Bindings** (`nomarr/persistence/database/*_aql.py`): Thin classes that own a `SafeDatabase` reference and bind one persistence domain. They call Tier 1 primitives or write custom AQL where the shape is genuinely domain-specific. These classes are private implementation details of `Database` and are never imported by components, workflows, or services.

**Tier 3 — Intent Sub-Facades** (`nomarr/persistence/api/`): Three typed attributes on `Database` that organize all public persistence operations by caller domain:
- `db.library` (`LibraryDb`) — libraries, files, tags
- `db.ml` (`MlDb`) — models, vectors, output streams
- `db.app` (`AppDb`) — file states, scan state, locks, worker claims, Navidrome mappings

Methods on each sub-facade are named for app intent (`add_library`, `count_files_by_tag`, `transition_file_states`), not persistence mechanics.

The legacy framework (`accessors.py`, `collections_base.py` verb surface, `constructor/`, `query_specs.py`, `query_templates.py`) is deleted in a clean cut. Cascade deletion is replaced by explicit handwritten delete operations in the relevant Tier 2 bindings — each entity's removal knows what it cleans up. Graph traversals remain as custom AQL in Tier 2 bindings; no generic traversal primitives are added. `DatabaseLike` is deleted alongside the legacy layer.

## Consequences

- Components and workflows access persistence only through `db.library`, `db.ml`, or `db.app`. Persistence mechanics are invisible to callers.
- The three sub-facades organize operations by how callers think about data, not by storage layout. Where an operation crosses collection boundaries, persistence resolves it internally.
- The legacy framework is deleted, not deprecated. Migration uses the clean-cut approach: build the new structure, delete the legacy layer, follow compiler errors. Self-documenting legacy calls make callsite migration straightforward.
- `cascade.py`, `EDGES` metadata, and cascade compilation are deleted. Each entity's remove operation explicitly lists what it deletes.
- All new persistence operations default to reusing Tier 1 primitives. Custom AQL is written in Tier 2 only when no primitive covers the shape cleanly.
- ADR-025 (schema-driven constructor) is superseded. ADR-030's core rule — call only through the `Database` facade — is preserved and strengthened, but the descriptor-based shape it blessed is retired.

## References

artifacts/designs/pending/DD-persistence-aql-primitives-intent-facade.md
