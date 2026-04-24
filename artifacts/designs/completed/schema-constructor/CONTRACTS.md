# Schema-Driven Persistence Constructor — Contracts Ledger

**Feature:** Schema-Driven Persistence Constructor  
**Design Document:** [DD-schema-driven-persistence-constructor](../../pending/DD-schema-driven-persistence-constructor.md)  
**Last Updated:** 2026-04-13  

---

## Architectural Rules

These rules are binding for all plans in this feature:

1. **100% schema-driven.** No hand-written AQL, no `custom_ops` escape hatch. Every operation derives from verbs + operator modifiers in the nested accessor chain.
2. **Runtime constructor.** No build-time codegen, no committed generated files. The constructor reads the schema at import time and dynamically builds namespace objects.
3. **Schema validates at import.** `SchemaValidationError` raised on violations — fast fail, no runtime surprises.
4. **`ann_search` restricted to TEMPLATE collections only.** Import-time check; `SchemaValidationError` if declared on any other type.
5. **`.get.one` only on `unique: true` fields.** Import-time enforcement; `AttributeError` if accessed on non-unique field.
6. **Always-list.** All mutation verbs accept `list[...]` — never a scalar. Pass `[item]` for a single value. No separate `_batch` or `bulk_` variants.
7. **Mandatory pagination** on all unbounded-result verbs (`get.many`, `get.in`, `get.like`, `collect`, `aggregate`, `traversal`, `ann_search`).
8. **Three-phase READ→REMOVE→INSERT** for `transition` verb (ADR-003 + ERR 1579).
9. **No lock-specific verb.** `locks` collection is standard CRUD with unique constraint.
10. **`in` is a Python reserved word.** Stored as `in_` internally, exposed as `.in()` via `__getattr__` aliasing.
11. **No compatibility shims.** All callers migrate to new nested accessor API.

---

## Constructor Contracts (Plan A)

### Schema Types — `persistence/schema.py`

 | Symbol | Type | Plan |
 | -------- | ------ | ------ |
 | `CollectionType` | `Enum(DOCUMENT, EDGE, STATE_GRAPH, TEMPLATE, INFRASTRUCTURE)` | A |
 | `Op` | `Enum(LT, GT, LTE, GTE, EQ, NEQ, NOT)` | A |
 | `FilterValue` | `int \ | float \ | bool \ | str` | A |
 | `FilterDict` | `dict[Op, FilterValue]` | A |
 | `AggResult` | `TypedDict(value=str, count=int)` | A |
 | `SchemaValidationError` | `RuntimeError` subclass | A |
 | `SCHEMA` | `dict[str, dict]` | A |

### SchemaConstructor — `persistence/constructor/builder.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `__init__` | `(self, db: SafeDatabase) -> None` | A |
 | `validate_schema` | `(self, schema: dict) -> None` raises `SchemaValidationError` | A |
 | `build_collection_namespace` | `(self, name: str, spec: dict) -> CollectionNamespace` | A |
 | `build` | `(self, schema: dict) -> dict[str, CollectionNamespace]` | A |

### CollectionNamespace — `persistence/constructor/namespaces.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `__init__` | `(self, db: SafeDatabase, collection_name: str, spec: CollectionSpec, schema: dict[str, Any], registry: dict[str, Any] \ | None = None) -> None` | A |
 | `insert` | `(self, docs: list[dict]) -> list[str]` | A |
 | `delete` | `(self, ids: list[str]) -> None` | A |
 | `cascade` | `(self, ids: list[str]) -> int` | A |
 | `count` | `(self) -> int` | A |
 | `get` | `CollectionGetNamespace` (callable shorthand + `.one.id()`, `.many.id()`) | A |
 | `truncate` | `(self) -> None` | A |
 | `transition` | `(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None` | A |
 | `traversal` | `(self, start: str \ | dict, edge: str, *, target_filter: dict \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `ann_search` | `(self, query_vector: list[float], limit: int, nprobe: int, *, filter: dict \ | None = None) -> list[dict]` | A |

### FieldNamespace — `persistence/constructor/namespaces.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `__init__` | `(self, db: SafeDatabase, collection_name: str, field_name: str, field_spec: dict, collection_operators: dict[str, list[str]] \ | None = None) -> None` | A |
 | `get` | `GetModifierNamespace` (callable shorthand) | A |
 | `count` | `(self, value: T) -> int` | A |
 | `collect` | `(self, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[T]` | CC-B |
 | `aggregate` | `(self, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[AggResult]` | CC-B |
 | `update` | `(self, match_value: T, fields: dict) -> None` | A |
 | `upsert` | `(self, docs: list[dict], match_field: str \ | list[str]) -> list[str]` | A |
 | `delete` | `(self, value: T) -> int` | A |

### GetModifierNamespace — `persistence/constructor/namespaces.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `__call__` | `(self, value: T) -> dict \ | None \ | list[dict]` (dispatches to one/many based on unique) | A |
 | `one` | `(self, value: T) -> dict \ | None` (only if `unique: true`) | A |
 | `many` | `(self, value: T, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `in_` | `(self, values: list[T] \ | FilterDict, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `by_filter` | `(self, filter_dict: dict[str, Any], *, limit: int \ | None = None, offset: int = 0) -> list[dict]` (only on `.many`) | A |
 | `like` | `(self, pattern: str, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |

### CascadeEngine — `persistence/constructor/cascade.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `cascade` | `(self, db: Any, collection_name: str, ids: list[str], cascade_targets: list[str], schema: dict, registry: dict | None = None) -> int` | A |

### Verb Templates — `persistence/constructor/verbs.py`

 | Function | Signature | Plan |
 | ---------- | ----------- | ------ |
 | `get_one_by_id` | `(db, collection, id) -> dict \ | None` (python-arango direct) | A |
 | `get_many_by_ids` | `(db, collection, ids) -> list[dict]` | A |
 | `get_one_by_field` | `(db, collection, field, value) -> dict \ | None` | A |
 | `get_many_by_field` | `(db, collection, field, value, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `get_many_by_filter` | `(db, collection, filter_dict: dict[str, Any], *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | CC-B |
 | `get_in_by_field` | `(db, collection, field: str, values: list[Any], *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | A |
 | `get_range_by_field` | `(db, collection, field: str, filter_dict: FilterDict, *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | A |
 | `get_like_by_field` | `(db, collection, field: str, pattern: str, *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | A |
 | `insert` | `(db, collection, docs: list[Document]) -> list[str]` | A |
 | `upsert_by_field` | `(db, collection, field: str \ | list[str], docs: list[Document]) -> list[str]` | A |
 | `update_by_field` | `(db, collection, field, value, fields) -> None` | A |
 | `update_by_filter` | `(db, collection, filter_dict: dict[str, Any], fields: Document) -> None` | CC-B |
 | `delete_by_ids` | `(db, collection, ids: list[str]) -> None` | A |
 | `delete_by_field` | `(db, collection, field, value) -> int` | A |
 | `delete_by_filter` | `(db, collection, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `count_all` | `(db, collection) -> int` | A |
 | `count_by_field` | `(db, collection, field, value) -> int` | A |
 | `count_by_filter` | `(db, collection, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `collect_field` | `(db, collection, field, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list` | CC-B |
 | `aggregate_field` | `(db, collection, field, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[AggResult]` | CC-B |
 | `traversal_by_id` | `(db, collection, start_id, edge, direction, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `traversal_by_filter` | `(db, collection, source_filter, edge, direction, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `traversal_by_filter_with_target_filter` | `(db, collection, source_filter, edge, direction, target_filter, *, limit: int \ | None = None, offset: int = 0) -> list[dict]` | A |
 | `ann_search` | `(db, collection, query_vector: list[float], limit: int, nprobe: int, *, filter: dict[str, Any] \ | None = None) -> list[Document]` | A |
 | `truncate` | `(db, collection_name: str) -> None` | A |

### VectorsTrackMaintenanceNamespace — `persistence/constructor/namespaces.py`

 | Method | Signature | Plan |
 | -------- | ----------- | ------ |
 | `__init__` | `(self, db: SafeDatabase, hot_collection_name: str, cold_collection_name: str) -> None` | A |
 | `drain_to_cold` | `(self) -> int` | A |
 | `ensure_cold_collection` | `(self) -> None` | A |
 | `drop_index` | `(self) -> None` | A |
 | `build_index` | `(self, *, embed_dim: int, nlists: int) -> None` | A |
 | `rebuild_index` | `(self, *, embed_dim: int, nlists: int) -> None` | A |
 | `get_stats` | `(self) -> dict[str, int \ | bool]` | A |

### Filter/Pagination — `persistence/constructor/filters.py`, `pagination.py`

 | Function | Signature | Plan |
 | ---------- | ----------- | ------ |
 | `build_in_filter` | `(field, values: list) -> tuple[str, dict]` (AQL fragment + bind vars) | A |
 | `build_comparison_filter` | `(field, filter_dict: FilterDict) -> tuple[str, dict]` | A |
 | `build_like_filter` | `(field, pattern: str) -> tuple[str, dict]` | A |
 | `inject_pagination` | `(query: str, limit: int \ | None, offset: int) -> tuple[str, dict[str, Any]]` | A |
 | `DEFAULT_LIMIT` | `int = 1000` | A |

---

## Migration Contracts (Plans B–D)

### MIGRATION-MAP.md — `artifacts/designs/parts/schema-constructor/MIGRATION-MAP.md`

*Maintained across Plans B–E and finalized in CC-F. Maps each legacy AQL module/pattern to its constructor-backed replacement.*

Format per collection:

```
### {collection_name}
 | Old Method | New Accessor | Notes | 
 | ------------ | ------------- | ------- | 
 | old_method(args) | db.collection.field.verb(args) | | 
```

---

## Type Stubs (Plan A, expanded in C–D)

### Base Protocols — `persistence/stubs/_base.pyi`

 | Symbol | Type | Plan |
 | -------- | ------ | ------ |
 | `GetOneProtocol` | `Protocol` | A |
 | `GetManyProtocol` | `Protocol` | A |
 | `GetModifierProtocol` | `Protocol` | A |
 | `AggResult` | `TypedDict` | A |

### Simple Collection Stubs (Plan A)

 | File | Collection | Plan |
 | ------ | ----------- | ------ |
 | `meta.pyi` | meta | A |
 | `migrations.pyi` | migrations | A |
 | `health.pyi` | health | A |
 | `sessions.pyi` | sessions | A |
 | `locks.pyi` | locks | A |
 | `vram_promises.pyi` | vram_promises | A |
 | `worker_claims.pyi` | worker_claims | A |
 | `worker_restart_policy.pyi` | worker_restart_policy | A |
 | `ml_capacity.pyi` | ml_capacity | A |
 | `library_pipeline_states.pyi` | library_pipeline_states | A |

### Complex Collection Stubs (Plans C–D)

 | File | Collection | Plan |
 | ------ | ----------- | ------ |
 | `tags.pyi` | tags | C |
 | `file_states.pyi` | file_states | D |
 | `libraries.pyi` | libraries | D |
 | `library_files.pyi` | library_files | D |
 | `library_contains_file.pyi` | library_contains_file | D |
 | `file_has_state.pyi` | file_has_state | D |
 | *(analytics/ML collections)* | *(per collection)* | E/F |

---

---

## Constructor Completion Contracts (Plan B) — Multi-Field Filter + Filtered Aggregate/Collect

### Filter Infrastructure — `persistence/constructor/filters.py`

 | Function | Signature | Plan |
 | ---------- | ----------- | ------ |
 | `build_equality_filter` | `(filter_dict: dict[str, Any]) -> tuple[str, dict[str, Any]]` | CC-B |

### New Verb Functions — `persistence/constructor/verbs.py`

 | Function | Signature | Plan |
 | ---------- | ----------- | ------ |
 | `get_many_by_filter` | `(db, collection, filter_dict: dict[str, Any], *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | CC-B |
 | `count_by_filter` | `(db, collection, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `delete_by_filter` | `(db, collection, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `update_by_filter` | `(db, collection, filter_dict: dict[str, Any], fields: Document) -> None` | CC-B |

### Extended Verb Signatures — `persistence/constructor/verbs.py`

 | Function | New Signature | Plan |
 | ---------- | -------------- | ------ |
 | `collect_field` | `(db, collection, field, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[Any]` | CC-B |
 | `aggregate_field` | `(db, collection, field, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[AggResult]` | CC-B |

### Namespace Extensions — `persistence/constructor/namespaces.py`

 | Class | Method | Signature | Plan |
 | ------- | -------- | ----------- | ------ |
 | `IdGetManyNamespace` | `by_filter` | `(self, filter_dict: dict[str, Any], *, limit: int \ | None = None, offset: int = 0) -> list[Document]` | CC-B |
 | `CollectionNamespace` | `_count_by_filter` | `(self, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `CollectionNamespace` | `_delete_by_filter` | `(self, filter_dict: dict[str, Any]) -> int` | CC-B |
 | `CollectionNamespace` | `_update_by_filter` | `(self, filter_dict: dict[str, Any], fields: Document) -> None` | CC-B |
 | `FieldNamespace` | `_collect` | `(self, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[Any]` | CC-B |
 | `FieldNamespace` | `_aggregate` | `(self, *, filter: dict[str, Any] \ | None = None, limit: int \ | None = None, offset: int = 0) -> list[AggResult]` | CC-B |

---

---

## Constructor Completion Contracts (Plan C) — Raw AQL Elimination: Tags

### Schema Capability Additions — `persistence/schema.py`

 | Collection | Field | Added Capability | Reason | Plan |
 | ------------ | ------- | ----------------- | -------- | ------ |
 | `song_has_tags` | `_to` | `collect` | Orphan detection needs distinct `_to` values | CC-C |
 | `tag_model_output` | `_from` | `collect` | Orphan detection needs distinct `_from` values | CC-C |

### Verb Usage Map — Tag Components

Part C creates no new verbs. It consumes verbs from Parts A and B:

 | Component Function | Constructor Verbs Used | Plan |
 | ------------------- | ---------------------- | ------ |
 | `find_or_create_tag` | `tags.value.upsert(docs, match_field=["rel", "value"])` | CC-C |
 | `resolve_tag_ids` | `tags.get.many.by_filter({"rel": ..., "value": ...})` | CC-C |
 | `_find_song_rel_edge_ids` | `song_has_tags._from.get.many(...)`, `tags.get(...)` | CC-C |
 | `cleanup_orphaned_tags` | `tags._id.collect(...)`, `song_has_tags._to.collect(...)`, `tag_model_output._from.collect(...)`, `tags.cascade(...)` | CC-C |
 | `get_orphaned_tag_count` | Same as `cleanup_orphaned_tags` minus cascade | CC-C |
 | `get_song_tags` | `library_files.traversal(song_id, "song_has_tags")` | CC-C |
 | `get_nomarr_tags_bulk` | `library_files.traversal(file_id, "song_has_tags")` | CC-C |
 | `list_songs_for_tag` | `song_has_tags._to.get.many(tag_id, limit, offset)` | CC-C |
 | `list_tags_by_rel` | `tags.rel.get.many(...)`, `song_has_tags.count_by_filter({"_to": ...})` | CC-C |
 | `count_tags_by_rel` | `tags.rel.get.many(...)` | CC-C |
 | `get_file_ids_matching_tag` | `tags.rel.get.many(...)`, `tags.traversal(tag_id, "song_has_tags")` | CC-C |
 | `get_file_ids_for_tags` | `tags.get.many.by_filter(...)`, `tags.traversal(...)`, `libraries.traversal(...)` | CC-C |
 | `get_file_ids_for_mood_tags` | `tags.get.many.by_filter(...)`, `tags.traversal(...)` | CC-C |
 | `get_distinct_tag_values_for_files` | `library_files.traversal(file_id, "song_has_tags")` | CC-C |
 | `get_tag_values_grouped_by_file` | `library_files.traversal(file_id, "song_has_tags")` | CC-C |
 | `get_tag_songs_with_metadata` | `tags.traversal(tag_id, "song_has_tags")`, `library_files.traversal(...)` | CC-C |
 | `get_tag_value_counts` | `tags.rel.get.many(...)`, `song_has_tags.count_by_filter(...)` | CC-C |
 | `get_all_tag_stats_batched` | `tags.rel.collect(...)`, `tags.rel.get.many(...)`, `song_has_tags.count_by_filter(...)` | CC-C |
 | `get_tag_frequencies` | `tags.rel.collect(...)`, `tags.rel.get.many(...)`, `song_has_tags.count_by_filter(...)` | CC-C |
 | `get_library_stats` | `libraries.traversal(...)` or `library_files._id.collect(...)` | CC-C |
 | `get_year_distribution` | `tags.get.many.by_filter({"rel": "year"})`, `song_has_tags.count_by_filter(...)` | CC-C |
 | `get_genre_distribution` | `tags.get.many.by_filter({"rel": "genre"})`, `song_has_tags.count_by_filter(...)` | CC-C |

---

## Constructor Completion Contracts (Plan D) — Raw AQL Elimination: Library

### Schema Capability Additions — `persistence/schema.py`

 | Collection | Field | Added Capability | Reason | Plan |
 | ------------ | ------- | ----------------- | -------- | ------ |
 | `file_has_state` | `_from` | `collect` | Bulk state queries need distinct `_from` values | CC-D |
 | `file_has_state` | `_to` | `collect` | State vertex enumeration | CC-D |
 | `library_contains_file` | `_from` | `delete`, `collect` | Library cascade and file-to-library lookups | CC-D |
 | `library_contains_file` | `_to` | `collect` | Batch library-file queries | CC-D |

### Verb Usage Map — Library Components

Part D creates no new verbs. It consumes verbs from Parts A and B:

 | Component Function | Constructor Verbs Used | Plan |
 | ------------------- | ---------------------- | ------ |
 | `upsert_library_file` | `db.library_files.path.get(...)`, `db.library_files.insert(...)`, `db.library_files._id.update(...)`, `db.library_contains_file._to.upsert(...)` | CC-D |
 | `upsert_batch` (edge upsert) | `db.library_contains_file._to.upsert(edge_docs, match_field=["_from", "_to"])` | CC-D |
 | `bulk_delete_files` | `db.song_has_tags._from.delete(file_id)` per file, `db.library_contains_file._to.delete(file_id)` per file | CC-D |
 | `get_file_library_key` | `db.library_contains_file._to.get.many(file_id, limit=1)` | CC-D |
 | `initialize_file_states` | `db.file_has_state.insert(edge_docs)` | CC-D |
 | `clear_all_states` | `db.file_has_state._from.delete(file_id)` | CC-D |
 | `discover_next_untagged_file` | `db.file_states.traversal(...)`, `db.worker_claims.get.many.by_filter(...)` | CC-D |
 | `count_untagged_files` | `db.file_states.traversal(STATE_NOT_TAGGED, "file_has_state")`, `db.libraries.traversal(...)` | CC-D |
 | `get_errored_file_ids` | `db.file_has_state._to.get.many(STATE_ERRORED, ...)`, `db.libraries.traversal(...)` | CC-D |
 | `get_uncalibrated_tagged_file_ids` | `db.file_states.traversal(...)` (×3), `db.libraries.traversal(...)` | CC-D |
 | `get_calibration_status_by_library` | `db.file_states.traversal(...)` (×2), `db.libraries.traversal(...)` per library | CC-D |
 | `get_files_with_incomplete_tags` | `db.file_states.traversal(STATE_TAGGED, ...)`, `db.library_files.traversal(file_id, "song_has_tags")` | CC-D |
 | `bulk_set_not_calibrated` | `db.file_has_state._to.get.many(STATE_CALIBRATED, ...)`, `db.file_states.transition(...)` | CC-D |
 | `bulk_set_tags_stale` | `db.file_has_state._to.get.many(STATE_TAGS_CURRENT, ...)`, `db.libraries.traversal(...)`, `db.file_states.transition(...)` | CC-D |
 | `get_files_by_ids_with_tags` | `db.library_files.get(file_id)`, `db.library_files.traversal(file_id, "song_has_tags")`, `db.library_contains_file._to.get.many(...)` | CC-D |
 | `get_library_file` | `db.libraries.traversal(...)` or `db.library_files.normalized_path.get.many(...)`, `db.library_files.path.get(...)` | CC-D |
 | `list_library_files` | `db.libraries.traversal(...)` or `db.library_files.get.many.by_filter({}, ...)` | CC-D |
 | `search_library_files_with_tags` | `db.library_files.get.many.by_filter(...)`, `db.file_states.traversal(...)`, `db.tags.get.many.by_filter(...)`, `db.library_files.traversal(file_id, "song_has_tags")` | CC-D |
 | `get_library_stats` | `db.libraries.traversal(...)` or `db.library_files.get.many.by_filter(...)` | CC-D |
 | `get_artist_album_frequencies` | `db.library_files.artist.aggregate(...)`, `db.library_files.album.aggregate(...)` | CC-D |
 | `clear_library_data` | `db.segment_scores_stats.truncate()`, `db.song_has_tags.truncate()`, `db.library_files._id.collect(...)` + `delete(...)` | CC-D |
 | `search_files_by_tag` | `db.tags.rel.get.many(...)`, `db.song_has_tags._to.get.many(...)`, `db.library_files.traversal(...)` | CC-D |
 | `get_tracks_for_matching` | `db.libraries.traversal(...)`, `db.library_files.traversal(file_id, "song_has_tags")` | CC-D |

---

## Constructor Completion Contracts (Plan E) — Raw AQL Elimination: Analytics + ML

### Schema Capability Additions — `persistence/schema.py`

 | Collection | Field | Added Capability | Reason | Plan |
 | ------------ | ------- | ----------------- | -------- | ------ |
 | `ml_models` | `_id` | `collect` | Full document scan via collect+get.many for `list_registered_models` | CC-E |
 | `ml_model_outputs` | `_key` | `update` | Key-addressed label updates in `update_model_output_label` | CC-E |
 | `model_has_output` | `_key` (new field) | `get`, `upsert` (unique) | Edge upsert by _key in `ensure_model_outputs` | CC-E |
 | `model_has_calibration` | `_key` (new field) | `get`, `upsert` (unique) | Edge upsert by _key in `save_calibration_state` | CC-E |
 | `vectors_track` (hot) | `_id` | `collect` | Enumerate hot docs for drain decomposition | CC-E |
 | `vectors_track` (cold) | `_id` | `collect` | Enumerate cold docs for backfill decomposition | CC-E |

### Persistence Additions — `persistence/constructor/namespaces.py`

 | Class | Method | Signature | Plan |
 | ------- | -------- | ----------- | ------ |
 | `VectorsTrackMaintenanceNamespace` | `drop_index` | `(self) -> None` | CC-E |
 | `VectorsTrackMaintenanceNamespace` | `build_index` | `(self, *, embed_dim: int, nlists: int) -> None` | CC-E |

### Verb Usage Map — Analytics + ML Components

Part E creates no new verbs. It consumes verbs from Parts A and B:

 | Component Function | Constructor Verbs Used | Plan |
 | ------------------- | ---------------------- | ------ |
 | `get_mood_and_tier_tags_for_correlation` | `tags.rel.get.many(...)`, `song_has_tags._to.get.many(...)`, `tags.rel.collect(...)` | CC-E |
 | `get_mood_distribution_data` | `tags.rel.get.many(...)`, `song_has_tags._to.get.many(...)`, `libraries.traversal(...)` | CC-E |
 | `get_mood_coverage` | `tags.rel.get.many(...)`, `song_has_tags._to.get.many(...)`, `libraries.traversal(...)` | CC-E |
 | `get_mood_balance` | `tags.rel.get.many(...)`, `song_has_tags._to.get.many(...)`, `libraries.traversal(...)` | CC-E |
 | `get_top_mood_pairs` | `tags.rel.get.many(...)`, `song_has_tags._to.get.many(...)`, `libraries.traversal(...)` | CC-E |
 | `get_sparse_histogram` | `ml_models.get(...)`, `tags.rel.collect(...)`, `tags.get.many.by_filter(...)` | CC-E |
 | `save_calibration_state` | `calibration_state._key.upsert(...)`, `model_has_calibration._key.upsert(...)` | CC-E |
 | `load_all_calibration_states` | `calibration_state._id.collect(...)`, `calibration_state.get.many(...)`, `model_has_calibration._key.get(...)`, `ml_models.get(...)` | CC-E |
 | `delete_calibration_state` | `calibration_state.delete(...)`, `model_has_calibration.delete(...)` | CC-E |
 | `drain_hot_to_cold` | `hot._id.collect(...)`, `hot.get(...)`, `song_has_tags._from.get.many(...)`, `tags.get(...)`, `cold._key.upsert(...)`, `file_has_vectors._to.delete(...)`, `file_has_vectors.insert(...)`, `hot.truncate()` | CC-E |
 | `backfill_genres` | `cold._id.collect(...)`, `cold.get(...)`, `song_has_tags._from.get.many(...)`, `tags.get(...)`, `cold._key.update(...)` | CC-E |
 | `verify_hot_empty` | `maintenance.get_stats()` | CC-E |
 | `drop_cold_vector_index` | `maintenance.drop_index()` | CC-E |
 | `has_vector_index` | `maintenance.get_stats()` | CC-E |
 | `build_cold_vector_index` | `maintenance.build_index(...)` | CC-E |
 | `rebuild_cold_vector_index` | `maintenance.rebuild_index(...)` | CC-E |
 | `get_cold_track_vector` | `maintenance.get_stats()`, `cold.get_vector(...)` | CC-E |
 | `list_hot_vector_targets` | `maintenance.get_stats()` | CC-E |
 | `compute_promotion_nlists` | `maintenance.get_stats()` | CC-E |
 | `list_registered_models` | `ml_models._id.collect(...)`, `ml_models.get.many(...)` | CC-E |
 | `update_model_output_label` | `ml_model_outputs._key.update(...)` | CC-E |
 | `ensure_model_outputs` | `ml_model_outputs._key.get(...)`, `ml_model_outputs.insert(...)`, `model_has_output._key.upsert(...)` | CC-E |
 | `delete_model_outputs_for_model` | `ml_models.traversal(...)`, `model_has_output.delete(...)`, `ml_model_outputs.delete(...)` | CC-E |

---

## Collections by Plan

 | Plan | Collections |
 | ------ | ------------ |
 | B | meta, migrations, health, sessions, locks, vram_promises, worker_claims, worker_restart_policy, ml_capacity, library_pipeline_states |
 | C | tags, song_has_tags, tag_model_output (schema-cap sync for tag cleanup) |
 | D | libraries, library_folders, library_files, library_contains_file, file_states, file_has_state |
 | E | calibration_state, calibration_history, ml_models, ml_model_outputs, model_has_calibration, model_has_output, navidrome_tracks, navidrome_playcounts, segment_scores_stats, tag_model_output, vectors_track, file_has_vectors |
 | F | cleanup only — no new runtime collections |

---

## Constructor Completion Contracts (Plan F) — Cleanup

### Deletions — `persistence/database/`

All legacy AQL files and Operations classes are deleted:

 | Target | Type | Plan |
 | -------- | ------ | ------ |
 | `library_files_aql/` | directory (4 files) | CC-F |
 | `tags_aql/` | directory (empty) | CC-F |
 | `vectors_track_aql/` | directory (3 files) | CC-F |
 | `calibration_history_aql.py` | file | CC-F |
 | `calibration_state_aql.py` | file | CC-F |
 | `libraries_aql.py` | file | CC-F |
 | `ml_capacity_aql.py` | file | CC-F |
 | `ml_model_outputs_aql.py` | file | CC-F |
 | `ml_models_aql.py` | file | CC-F |
 | `navidrome_playcounts_aql.py` | file | CC-F |
 | `navidrome_tracks_aql.py` | file | CC-F |
 | `segment_scores_stats_aql.py` | file | CC-F |
 | `tag_model_output_aql.py` | file | CC-F |
 | `README.md` | file | CC-F |
 | `__init__.py` | rewritten to empty | CC-F |

### Stub Regeneration — `persistence/stubs/`

All `.py` stubs regenerated as `.pyi` with final verb signatures:

 | Old File (.py) | New File (.pyi) | Plan |
 | --------------- | ---------------- | ------ |
 | `calibration_history.py` | `calibration_history.pyi` | CC-F |
 | `calibration_state.py` | `calibration_state.pyi` | CC-F |
 | `ml_model_outputs.py` | `ml_model_outputs.pyi` | CC-F |
 | `ml_models.py` | `ml_models.pyi` | CC-F |
 | `navidrome_playcounts.py` | `navidrome_playcounts.pyi` | CC-F |
 | `navidrome_tracks.py` | `navidrome_tracks.pyi` | CC-F |
 | `segment_scores_stats.py` | `segment_scores_stats.pyi` | CC-F |
 | `tag_model_output.py` | `tag_model_output.pyi` | CC-F |
 | `vectors_track.py` | `vectors_track.pyi` | CC-F |

### Artifact Updates

 | Artifact | Change | Plan |
 | ---------- | -------- | ------ |
 | `CONTRACTS.md` | Rule 6 → "Always-list", final verb signatures | CC-F |
 | `MIGRATION-MAP.md` | Created with all old→new mappings | CC-F |
 | `docs/dev/workers.md` | Remove `worker_claims_aql.py` reference | CC-F |
 | `docs/dev/qc.md` | Update AQL examples to constructor patterns | CC-F |
 | `docs/dev/naming.md` | Remove `*Operations / *_aql` convention | CC-F |
 | `docs/dev/architecture.md` | Replace legacy `persistence/database/` guidance with constructor-based persistence layer notes | CC-F |
 | `docs/dev/calibration-troubleshooting.md` | Replace deleted calibration AQL module reference with constructor-backed calibration persistence entry point | CC-F |
 | `docs/dev/migrations.md` | Verified raw `db.aql.execute(...)` remains intentionally valid inside migrations | CC-F |
