# ADR-024: AQL Subpackage Naming Convention and Collection Origination Principle

**Status:** Accepted  
**Date:** 2026-04-09  
**Tags:** persistence, architecture, aql, naming  
**Source Log:** agent#L1  

## Context

The `nomarr/persistence/database/` layer contains 25+ AQL collection modules totaling ~8,000 lines of active code. Four collections (`library_files`, `tags`, `file_states`, `vectors_track`) have already been split into subpackages using generic module names (`crud.py`, `queries.py`, `stats.py`). The remaining 21 are single-file modules ranging from 130–495 lines.

Several problems have surfaced:

1. **Tab ambiguity.** With 4+ subpackages using identical filenames (`crud.py`, `queries.py`), editor tabs and grep results lack collection context.

2. **Methods in wrong modules.** Operations are grouped by vague theme rather than by which collection they originate from. Examples: `search_files_by_tag` (starts `FOR tag IN tags`) lives in `library_files_aql/stats.py`; `get_folder_rel_paths` (traverses to `library_folders`) lives in `library_files_aql/queries.py`; `clear_library_data` (bulk delete) lives in `stats.py`.

3. **Orchestration in persistence.** `library_files_aql/reconciliation.py` contains zero AQL against `library_files` — it orchestrates `file_states` + `worker_claims` via Python API, which is component-level work.

4. **Catch-all "queries" modules.** `library_files_aql/queries.py` (695 lines) and `tags_aql/queries.py` (586 lines) are bags of unrelated read operations that grow unbounded.

5. **No consistent rule** for deciding which AQL module owns a query, leading to duplication and misplacement across files.

This decision responds to ASR-017 (complete, stable persistence API) and ASR-018 (well-defined layer boundaries).

## Decision

### 1. All AQL Collections Use Subpackages

Every AQL collection module — regardless of current line count — is structured as a subpackage directory. The persistence API completion work (ASR-017) will grow all collections past any reasonable single-file threshold, making single-file modules a temporary state that generates migration churn later. Convert them all now.

### 2. Collection-Prefixed File Names

All AQL subpackage modules (except `__init__.py` and private helpers like `_constants.py`) are named `{collection}_{operation}.py`:

```
library_files_aql/
    __init__.py
    library_files_upsert.py
    library_files_update.py
    library_files_delete.py
    library_files_get_one.py
    library_files_get_many.py
    library_files_search.py
    library_files_stats.py
```

This ensures globally unique filenames across all 25+ AQL subpackages.

### 3. Standard Operation Categories

Each subpackage uses a fixed taxonomy of operation types. Not every collection needs all categories — only create modules that have methods to fill them:

 | Suffix | Responsibility |
 | -------- | --------------- |
 | `_upsert` | Insert or insert-or-update operations |
 | `_update` | Field-level updates on existing documents |
 | `_delete` | Document removal and cascade cleanup |
 | `_cascade` | Cross-collection cleanup triggered by deletes in this collection. ArangoDB lacks native cascading deletes, so this module handles referential integrity: deleting edges, related documents in other collections, and state cleanup when a document in this collection is removed. Only contains cascade detection and execution — the delete itself lives in `_delete` |
 | `_get_one` | Single document lookups by key, ID, or unique field |
 | `_get_many` | Bulk lookups by sets of keys/IDs/paths; folder-scoped batch fetches |
 | `_search` | Filtered, paginated queries with dynamic conditions |
 | `_set` | Edge-based state operations originating FROM this collection |
 | `_stats` | Aggregation, counting, frequency queries |

### 4. Collection Origination Principle

Each AQL subpackage owns queries whose **primary AQL operation originates from its collection**:

- **Writes** (UPSERT/UPDATE/REMOVE) belong to the collection being written to.
- **Reads** belong to whichever collection the primary `FOR ... IN` loop or `DOCUMENT()` call targets.
- **Edge traversals** belong to the collection of the traversal target (the result type), not the starting vertex.
- **Subqueries** referencing other collections (tag enrichment, state checks) do not change origination — they are implementation details of the owning query.

Examples under this rule:

- `search_files_by_tag` starts `FOR tag IN tags` → belongs in `tags_aql/tags_search.py`
- `get_folder_rel_paths` traverses OUTBOUND to `library_folders` → belongs in `library_folders_aql`
- `get_files_by_ids_with_tags` starts `DOCUMENT(file_id)` → belongs in `library_files_aql` (tag join is subquery)

### 5. No Orchestration in Persistence

AQL modules contain only AQL queries and minimal Python to build/execute them. Multi-collection orchestration (e.g., "claim files, check states, update claims") belongs in components, not persistence. If a method in an AQL module calls `self.parent_db.other_collection.method()` as its primary logic (not as a side-effect of a write), it is misplaced.

## Consequences

**Positive:**

- Editor tabs, stack traces, and grep results are unambiguous across 25+ collections.
- The origination principle provides a deterministic answer to "where does this query go?" — no judgment calls.
- Operation type taxonomy prevents catch-all modules from re-emerging.
- All collections are structured uniformly — no migration churn when small modules inevitably grow past a threshold.

**Negative:**

- File count in `persistence/database/` increases significantly (more `__init__.py` files, more directories).
- Some queries serve a domain concept that spans collections (e.g., "find files by tag") — the origination rule may feel unintuitive to callers. This is acceptable because callers go through `Database` (the facade), not individual AQL modules.

## References

- ASR-017: Persistence Layer Must Expose a Complete, Stable API Surface
- ASR-018: Application Layer Boundaries Must Be Stable and Well-Defined
- Existing subpackages: library_files_aql, tags_aql, file_states_aql, vectors_track_aql
