# Constructor Completion — Always-List Signatures, Compound Upsert, Multi-Field Filters, and Raw AQL Elimination — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-12  

**Related Documents:**

- [Schema-Driven Persistence Constructor Supersedes Hand-Written AQL Conventions]() —
- [Pure Boolean State Graph for File Processing Pipeline]() —
- [Schema Refactor V1 — Graph Normalization]() —
- [Schema Constructor Contracts Ledger]() —
- [Research: constructor-completion scope and raw AQL census]() —

---

## Scope

nomarr/persistence/constructor/ (verb improvements), nomarr/components/ (raw AQL migration), nomarr/persistence/database/ (cleanup), nomarr/persistence/stubs/ (type stub updates), artifacts/designs/parts/schema-constructor/ (contracts + migration map)

---

## Problem Statement

The schema-driven persistence constructor infrastructure is complete and all 37 collections are wired, but the job is unfinished in three areas:

1. **Type signature inconsistency.** Mutation verbs use union types (`Document | list[Document]`, `str | list[str]`) creating branching code paths, compound test surfaces, and caller confusion. Rule 6 ("implicit bulk") was meant to simplify, but union returns create the same complexity it was supposed to eliminate.

2. **Verb capability gaps.** `upsert_by_field` matches on a single field only — compound-key upsert (e.g., tags matched by `rel + value`) requires falling back to raw AQL. Similarly, `get_many_by_field`, `count_by_field`, `delete_by_field`, and `update_by_field` filter on one field only — multi-field equality needs raw AQL. `collect_field` and `aggregate_field` have no filter parameter, forcing raw AQL when you need filtered aggregation.

3. **~92 raw AQL calls remain in components.** Component "helpers" were renamed during Plans B–D but their internals still bypass the constructor via `db.db.aql.execute()` and `db.db.collection()`. These violate ADR-025 Rule 2 (verb-only access) and Rule 4 (no hand-written AQL). Until these are eliminated, the constructor is infrastructure without adoption.

---

## Architecture

## Requirement 1: Always-List Type Signatures

### Change

All mutation verbs switch from union types to list-only signatures. Return types become always-list.

**Verbs affected:**

 | Verb | Current Signature | New Signature |
 | ------ | ------------------- | --------------- |
 | `insert` | `(db, col, doc: Document \ | list[Document]) -> str \ | list[str]` | `(db, col, docs: list[Document]) -> list[str]` |
 | `upsert_by_field` | `(db, col, field, doc: Document \ | list[Document]) -> str \ | list[str]` | `(db, col, field, docs: list[Document]) -> list[str]` |
 | `delete_by_ids` | `(db, col, ids: str \ | list[str]) -> None` | `(db, col, ids: list[str]) -> None` |
 | `transition` (CollectionNamespace) | `(self, ids: str \ | list[str], ...) -> None` | `(self, ids: list[str], ...) -> None` |
 | `cascade` (CollectionNamespace) | `(self, ids: str \ | list[str]) -> int` | `(self, ids: list[str]) -> int` |

**Namespace wrappers** in `CollectionNamespace` and `FieldNamespace` follow the same pattern — their `_insert`, `_delete`, `_cascade`, `_transition`, `_upsert` methods accept only `list[...]`.

**GET verbs are unchanged:** `get_one_by_id` returns `Document | None`, `get_many_by_ids` returns `list[Document]`. "One" vs "many" is semantic intent, not a degenerate list case.

**Rule 6 reworded in CONTRACTS.md:**  
Old: "Implicit bulk. Single verb handles scalar and list inputs."  
New: "Always-list. All mutation verbs accept `list[...]` — never a scalar. Pass `[item]` for a single value. No separate `_batch` or `bulk_` variants."

### Caller Migration

Every existing caller of `insert`, `upsert_by_field`, `delete_by_ids`, `transition`, and `cascade` that passes a scalar must wrap it: `doc` → `[doc]`, `id` → `[id]`. Return handling changes from `str` to `list[str]` — callers that expect a scalar use `result[0]`.

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `persistence/constructor/verbs.py` | persistence | Remove union dispatch, list-only logic |
 | `persistence/constructor/namespaces.py` | persistence | Update wrapper signatures |
 | `persistence/stubs/*.pyi` | persistence | Update type annotations |
 | All component callers | components | Wrap scalars, handle list returns |

---

## Requirement 2: Compound-Key Upsert

### Change

`upsert_by_field` currently accepts `field: str` for single-field matching. Extend to accept `field: str | list[str]` for compound key matching.

**New signature:**

```
upsert_by_field(db, col, field: str | list[str], docs: list[Document]) -> list[str]
```

When `field` is a `list[str]`, the generated AQL uses a compound UPSERT search expression:

```aql
FOR doc IN @docs
  UPSERT { [@f0]: doc[@f0], [@f1]: doc[@f1] }
  INSERT doc
  UPDATE doc
  IN @@col
  RETURN NEW._id
```

Each document in `docs` must contain all fields listed in `field`.

**No new verb.** This extends the existing `upsert_by_field` verb. The `FieldNamespace._upsert` method already receives `match_field` — the change makes `match_field` accept a list.

### Primary Use Case

Tags have compound key `(name, value)`:

```python
db.tags.rel.upsert([{"rel": "genre", "value": "rock"}], match_field=["rel", "value"])
```

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `persistence/constructor/verbs.py` | persistence | Compound UPSERT AQL generation |
 | `persistence/constructor/namespaces.py` | persistence | Forward list to verb |

---

## Requirement 3: Multi-Field Equality Filter

### Change

Verbs that currently filter on a single field (`field: str, value: Any`) gain an alternate call path accepting a dict for multi-field equality: `filter: dict[str, Any]`.

**Affected verbs:**

 | Verb | Current Filter | Added Filter |
 | ------ | --------------- | -------------- |
 | `get_many_by_field` | `field, value` | `filter: dict[str, Any]` |
 | `count_by_field` | `field, value` | `filter: dict[str, Any]` |
 | `delete_by_field` | `field, value` | `filter: dict[str, Any]` |
 | `update_by_field` | `field, value, fields` | `filter: dict[str, Any], fields` |

**Implementation approach:** New companion verb functions (`get_many_by_filter`, `count_by_filter`, `delete_by_filter`, `update_by_filter`) that accept `filter: dict[str, Any]` and generate multi-field `FILTER doc.f1 == @v1 AND doc.f2 == @v2` AQL. These are surfaced through the existing namespace accessor chain — the namespace detects dict vs scalar and dispatches to the correct verb.

**Namespace access pattern:**

```python
# Single-field (existing)
db.tags.rel.get.many("genre")

# Multi-field (new — called on collection, not field)
db.tags.get.many.by_filter({"rel": "genre", "value": "rock"})
```

The multi-field filter is a **collection-level** operation, not a field-level one, because it crosses field boundaries. A new `by_filter` accessor on `CollectionGetNamespace.many` handles this.

### Filter Infrastructure

A new `build_equality_filter(filter_dict: dict[str, Any]) -> tuple[str, dict[str, Any]]` function in `filters.py` generates the AQL fragment:

```aql
doc.@f0 == @v0 AND doc.@f1 == @v1
```

with bind variables for both field names and values.

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `persistence/constructor/filters.py` | persistence | `build_equality_filter` function |
 | `persistence/constructor/verbs.py` | persistence | `*_by_filter` verb variants |
 | `persistence/constructor/namespaces.py` | persistence | `by_filter` accessor on collection get/count/delete/update |

---

## Requirement 4: Filtered Aggregate/Collect

### Change

`collect_field` and `aggregate_field` gain an optional `filter: dict[str, Any]` keyword argument. When provided, a `FILTER` clause is injected before the `COLLECT` or `RETURN DISTINCT`.

**New signatures:**

```
collect_field(db, col, field, *, filter: dict[str, Any] | None = None, limit, offset) -> list[Any]
aggregate_field(db, col, field, *, filter: dict[str, Any] | None = None, limit, offset) -> list[AggResult]
```

**Generated AQL with filter:**

```aql
FOR doc IN @@col
  FILTER doc.@f0 == @v0
  COLLECT value = doc.@field WITH COUNT INTO cnt
  SORT cnt DESC
  LIMIT @offset, @limit
  RETURN { value, count: cnt }
```

The filter reuses `build_equality_filter` from Requirement 3.

**Namespace forwarding:** `FieldNamespace._collect` and `FieldNamespace._aggregate` accept the optional `filter` kwarg and forward to the verb.

### Primary Use Case

Tag statistics filtered by relation:

```python
db.tags.value.collect(filter={"rel": "genre"}, limit=100)
db.tags.value.aggregate(filter={"rel": "genre"}, limit=50)
```

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `persistence/constructor/verbs.py` | persistence | Add filter kwarg to collect/aggregate |
 | `persistence/constructor/namespaces.py` | persistence | Forward filter from namespace |

---

## Requirement 5: Raw AQL Elimination

### Approach

With Requirements 1–4 in place, systematically rewrite all ~92 raw AQL calls in component files. The calls fall into categories:

**Category A — Direct verb replacements (~35 calls)**
Single-collection CRUD that maps 1:1 to an existing or improved verb.
Examples: `get_one_by_id`, `get_many_by_field`, `insert`, `delete_by_ids`, `count_by_field`, `truncate`.

**Category B — Multi-verb compositions (~25 calls)**
Cross-collection joins (file → edge → tag) that decompose into sequential verb calls with Python logic between them.
Examples: `get_song_tags` (traversal → collect tags), `set_song_tags` (delete edges → upsert tags → insert edges), `relink_tag_edges`.

**Category C — Filtered queries using new dict-filter or filtered aggregate (~15 calls)**
Queries with multi-field WHERE clauses or filtered COLLECT/aggregate.
Examples: `list_tags_by_rel` (filter by rel + optional search), `get_tag_value_counts` (aggregate by rel).

**Category D — Complex multi-step or dynamic queries (~17 calls)**
Queries with dynamic WHERE clause construction, subqueries, or cross-collection analytics.
Examples: `search_library_files_with_tags` (dynamic text search + tag join), `list_library_files` (variable filters), `discover_next_untagged_file` (state graph traversal with exclusion), `get_sparse_histogram` (cross-collection analytics), `drain_hot_to_cold` (UPSERT with enrichment join).

For Category D, the query logic (bin math, search scoring, dynamic filter construction) moves to Python. Each AQL call becomes a verb call; orchestration between calls is Python code in the component function.

### File-by-File Plan

 | File | Raw Calls | Category Mix | Key Verbs Needed |
 | ------ | ----------- | ------------- | ------------------ |
 | `library_file_query_comp.py` | ~27 | A(8) B(5) C(4) D(10) | get, traversal, count, collect, truncate, dict-filter |
 | `library_file_state_comp.py` | ~15 | A(3) B(8) D(4) | transition, get_many_by_field, count_by_field, traversal |
 | `library_file_mutation_comp.py` | 5 | A(2) B(3) | insert, upsert, update, delete |
 | `tag_query_comp.py` | ~11 | A(2) B(4) C(3) D(2) | get, traversal, dict-filter, aggregate |
 | `tag_stats_comp.py` | ~8 | A(1) C(4) D(3) | aggregate, collect, dict-filter, filtered-aggregate |
 | `tag_write_comp.py` | 3 | B(3) | upsert (compound-key), get_many_by_field, delete |
 | `tag_cleanup_comp.py` | 2 | D(2) | traversal + Python orphan detection |
 | `mood_analysis_comp.py` | 7 | B(2) D(5) | traversal, aggregate, filtered-aggregate |
 | `ml_calibration_comp.py` | 1 | D(1) | Cross-collection histogram — verb composition |
 | `ml_calibration_state_comp.py` | 4 | A(4) | truncate, collection access via constructor |
 | `ml_vector_maintenance_comp.py` | 5 | D(5) | drain/genre-backfill need multi-verb + Python |

### Migration Order

1. **Tag components first** (tag_write, tag_query, tag_cleanup, tag_stats) — highest verb coverage, validates compound-key upsert and dict-filter
2. **Library mutation** — straightforward, validates always-list signatures
3. **Library state** — validates bulk transition patterns
4. **Library query** — heaviest file, most Category D, done last in library group
5. **Mood analysis** — mostly graph traversal compositions
6. **ML calibration** — small, some db.db bypasses to fix
7. **ML vectors** — drain_hot_to_cold is the most complex single migration

### db.db Bypass Elimination

4 calls in `ml_calibration_state_comp.py` use `db.db.collection(...)` directly:

- `db.db.collection("model_has_calibration")` → `db.model_has_calibration` (collection namespace)
- `db.db.collection("ml_models")` → `db.ml_models` (collection namespace)
- `db.db.collection("calibration_state").truncate()` → `db.calibration_state.truncate()`
- `db.db.collection("calibration_history").truncate()` → `db.calibration_history.truncate()`

---

## Requirement 6: Cleanup

### Old AQL Helper Deletion

Once all component callers are migrated, delete legacy AQL files in `nomarr/persistence/database/`:

- `calibration_history_aql.py`
- `calibration_state_aql.py`
- `libraries_aql.py`
- `library_files_aql/` (directory)
- `ml_capacity_aql.py`
- `ml_models_aql.py`
- `ml_model_outputs_aql.py`
- `navidrome_playcounts_aql.py`
- `navidrome_tracks_aql.py`
- `segment_scores_stats_aql.py`
- `tags_aql/` (directory)
- `tag_model_output_aql.py`
- `vectors_track_aql/` (directory)

Also delete `__init__.py` re-exports and the `README.md` in that directory, then verify no remaining imports from `nomarr.persistence.database` outside of `db.py` itself.

### Artifact Updates

- **CONTRACTS.md**: Update all verb signatures (always-list), add compound-key upsert, add dict-filter verbs, add filtered aggregate/collect, update Rule 6 wording
- **MIGRATION-MAP.md**: Update with accurate old→new mappings for all migrated component functions
- **Type stubs**: Regenerate all `.pyi` files under `persistence/stubs/` to reflect new signatures
- **ADR-025**: No change needed — it already mandates verb-only access and no hand-written AQL

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `persistence/database/*.py` | persistence | Delete legacy AQL files |
 | `persistence/stubs/*.pyi` | persistence | Regenerate type stubs |
 | `artifacts/designs/parts/schema-constructor/` | artifacts | Update CONTRACTS.md, MIGRATION-MAP.md |

---

## Design Goals

1. **One code path.** Every mutation verb has exactly one input shape (list) and one output shape (list). No branching, no union dispatch, no conditional test coverage.
2. **Expressiveness parity.** The constructor verb set must handle every query pattern currently expressed as raw AQL — compound-key upsert, multi-field equality, filtered aggregation — without escape hatches.
3. **Zero raw AQL in components.** After completion, no component file contains `db.db.aql.execute()` or `db.db.collection()` calls. All persistence access goes through constructor namespaces.
4. **Backward compatibility within the constructor.** The constructor infrastructure (builder, metaclass, schema, cascade engine) is not redesigned. Changes are additive (new filter function, extended verb parameters) or narrowing (union → list-only).
5. **Clean artifact trail.** CONTRACTS.md reflects final signatures, MIGRATION-MAP.md traces every migration, type stubs match runtime behavior.

---

## Constraints

- Existing constructor infrastructure (builder, metaclass, schema, cascade engine, pagination) works and passed 1754 tests — do not redesign
- 11 architectural rules in CONTRACTS.md are binding (Rule 6 reworded, not removed)
- ERR 1579: no read+write same collection in single AQL — multi-step operations use separate verb calls
- ADR-003: three-phase state transitions (READ→REMOVE→INSERT) preserved in transition verb
- ADR-025: verb-only access, component-layer compositions, no hand-written AQL, schema is single source of truth
- No custom_ops escape hatch — every operation derives from verbs + filters
- File length limits per ADR-021: persistence files ≤200 lines, component files ≤400 lines

---

## Open Questions

1. **Category D query decomposition granularity.** Some complex queries (e.g., `search_library_files_with_tags` with dynamic text search + tag join + count) may produce slower multi-verb decompositions than the current single AQL. For alpha with small libraries this is acceptable — should we add a performance annotation for post-1.0 optimization?

2. **`drain_hot_to_cold` enrichment join.** The current AQL enriches each vector document with genres during drain by joining through 3 collections in one query. Decomposing this into verb calls means N+1-style lookups per document. The VectorsTrackMaintenanceNamespace already owns this operation — should it keep internal AQL as a sanctioned exception, or should it use verb composition despite the performance cost?

3. **Orphan tag detection.** `cleanup_orphaned_tags` needs to find tags with zero edges in both `song_has_tags` and `tag_model_output`. This is inherently a "NOT EXISTS subquery" pattern. Options: (a) two traversal calls + Python set difference, (b) a new `exists` verb modifier, (c) leave as the one sanctioned raw AQL. Recommendation: option (a) with Python set logic.

4. **`get_sparse_histogram` cross-collection analytics.** This query joins `song_has_tags` → `tags` with binning math. It's a one-off analytics query that doesn't map cleanly to any verb. Options: (a) verb composition with Python binning, (b) sanctioned raw AQL in calibration component. Recommendation: (a) — the binning math is pure Python anyway.

---
