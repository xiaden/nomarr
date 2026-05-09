# Contracts Ledger — Collection-First Query-Spec Persistence

Design doc: `artifacts/designs/pending/DD-collection-first-query-spec-persistence.md`
Parts README: `artifacts/designs/parts/collection-first-query-spec-persistence/README.md`

---

## Architectural Rules

- `Database` remains the only public persistence entry point.
- Generic persistence operations are collection-first; fields are criteria metadata, not first-class architectural namespaces.
- No new field-first APIs are added unless explicitly justified by design review.
- Query specs, capability families, template assets, and surface API are distinct layers and must not collapse back into one overloaded abstraction.
- Only true storage-native primitives keep dedicated persistence names.
- ANN search is presumptively storage-native; other special helpers must justify themselves or move above persistence.
- No raw AQL fragments are accepted from higher layers.
- AQL validation is required at spec/template level and must support parse/explain validation in tests/CI where practical.
- Runtime registration remains vector-only unless explicitly re-decided.
- Persistence remains single-step and returns storage-shaped results.

---

## Capability Families

| Family | Status | Notes |
|--------|--------|-------|
| Document read | implemented in Part A metadata | Generic collection-first reads with validated criteria |
| Document write | implemented in Part A metadata | Insert/update/upsert/delete family |
| Aggregation | implemented in Part A metadata | Count, aggregate, collect-like summaries |
| Relationship-native | implemented in Part A metadata | Traversal/cascade and any justified relationship-native primitives |
| State-native | implemented in Part A metadata | Kept only if transition survives stricter re-justification |
| ANN search | implemented in Part A metadata | True vector-native primitive |
| Administrative maintenance | implemented in Part A metadata | Narrow storage-maintenance primitives only |

---

## Query-Spec / Validation Contracts

| Symbol / Contract | Status | Notes |
|-------------------|--------|-------|
| `query_specs.py` public contracts | implemented in Part A | Capability metadata + validated criteria contracts |
| `query_templates.py` template registry | implemented in Part A | Fixed first-party AQL templates only |
| `aql_validation.py` validation helpers | implemented in Part A | Spec/template/bind-time validation + parse/explain hooks |
| Naming grammar enforcement | implemented in Part A | No new bespoke generic helper names |

---

## Compatibility / Migration Decisions

| Topic | Current Decision |
|------|------------------|
| Field accessors | Compatibility shims only; not normative architecture |
| Collection families | Internal scaffolding, not sacred public architecture |
| `transition` | Must be re-justified during implementation planning |
| Vector-branded helpers | Reclassify as generic, native, or higher-layer composition |

---

## Implemented Contracts

_Add actual implemented signatures, modules, helpers, and enforcement rules here after each completed plan._

### Plan A

**Created modules**

| Symbol | Module | Notes |
|--------|--------|-------|
| `CollectionFamily` | `nomarr.persistence.query_specs` | Closed enum: `DOCUMENT`, `EDGE`, `VECTOR`, `STATE_GRAPH` |
| `CapabilityFamily` | `nomarr.persistence.query_specs` | Closed enum including storage-native `ANN_SEARCH` |
| `QueryOperator` | `nomarr.persistence.query_specs` | Normalized operator taxonomy for validated criteria |
| `PublicNamingGrammar` | `nomarr.persistence.query_specs` | Enforces no new bespoke generic helper names at registry level |
| `ReadQuerySpec` / `WriteQuerySpec` / `AggregateQuerySpec` | `nomarr.persistence.query_specs` | Typed query descriptors for generic collection-first operations |
| `QueryTemplateId` | `nomarr.persistence.query_templates` | Fixed first-party AQL template identifiers |
| `validate_template_bind_contract()` | `nomarr.persistence.query_templates` | Rejects unknown IDs, incomplete/unexpected binds, and raw-AQL fragments |
| `iter_first_party_query_templates()` | `nomarr.persistence.query_templates` | Enumerates reviewed template assets |
| `materialize_collection_metadata()` | `nomarr.persistence.aql_validation` | Builds validation metadata from live collection instances |
| `validate_query_spec()` | `nomarr.persistence.aql_validation` | First-class spec validation with typed errors |
| `validate_spec_template_contract()` | `nomarr.persistence.aql_validation` | Confirms query-spec ↔ template compatibility |
| `validate_template_bindings()` | `nomarr.persistence.aql_validation` | Validates bind payload shape and completeness |
| `validate_bound_aql()` | `nomarr.persistence.aql_validation` | Checks materialized query/bind readiness |
| `validate_first_party_aql()` | `nomarr.persistence.aql_validation` | Parse/explain validation with explicit `SKIPPED` outcome when no live DB is available |
| `BaseCollection._query_collection_metadata()` | `nomarr.persistence.collections_base` | Internal metadata bridge for validation/template consumers only |
| `FieldAccessor._query_field_metadata()` | `nomarr.persistence.accessors` | Internal compatibility bridge only; not normative API growth |

**Tests added**

- `tests/unit/persistence/test_query_specs.py`
- `tests/unit/persistence/test_query_templates.py`
- `tests/unit/persistence/test_aql_validation.py`
- `tests/integration/test_persistence_aql_validation.py`

**Validation outcome**

- Exec-Manager reported `status: DONE`
- QA status: `PASS`
- Test analyzer: `PASS`
- Docs analyzer: `PASS`
- Reported validation: `1687` tests passing, `0` failures

### Plan B

**Created/modified modules**

| Symbol | Module | Notes |
|--------|--------|-------|
| `SupportsCollectionFirstSurface` | `nomarr.persistence.accessors` | Structural protocol for the collection-owned generic persistence surface |
| `CollectionGet` | `nomarr.persistence.accessors` | Normative read root exposed as `collection.get`; supports `__call__`, `.many`, `.in_`, `.gte`, `.lte`, `.like` |
| `CollectionDelete` | `nomarr.persistence.accessors` | Normative delete root exposed as `collection.delete`; supports `__call__`, `.in_`, `.unreferenced`, and holds the injected `cascade` slot |
| `FieldGet` | `nomarr.persistence.accessors` | Compatibility shim for equality/in_/gte/lte/like reads; delegates through `_build_field_read_query_spec()` into the collection root |
| `FieldDelete` | `nomarr.persistence.accessors` | Compatibility shim for equality and `in_` deletes; delegates through `_build_field_write_query_spec()` into the collection root |
| `FieldAccessor` | `nomarr.persistence.accessors` | Frozen compatibility wrapper exposing `get`, `delete`, `update`, `upsert`, `count`, and `collect`; no new surface growth |
| `_build_field_read_query_spec` / `_build_field_write_query_spec` / `_build_field_count_query_spec` / `_build_field_collect_query_spec` | `nomarr.persistence.accessors` | Internal spec builders for shim delegation only |
| `BaseCollection.__init__` | `nomarr.persistence.collections_base` | Wires `self.get = CollectionGet(self)` and `self.delete = CollectionDelete(self)` for every collection |
| `BaseCollection._collection_get` | `nomarr.persistence.collections_base` | Generic collection-first read implementation; auto-singleton on one EQ criterion over a registered unique field when there is no sort/pagination/`force_many` |
| `BaseCollection._collection_delete` | `nomarr.persistence.collections_base` | Generic collection-first delete implementation; empty criteria truncate, single EQ delegates to delete-by-field, single IN to delete-in-by-field, multi-EQ to filter delete, and non-EQ multi-criteria raise until a reviewed template exists |
| `BaseCollection.insert` | `nomarr.persistence.collections_base` | Template-backed generic insert via `DOCUMENT_WRITE_INSERT_MANY` |
| `BaseCollection.update` | `nomarr.persistence.collections_base` | Collection-owned update requiring at least one criterion; multi-criterion path is EQ-only via `_criteria_to_equality_filter()` |
| `BaseCollection.upsert` / `upsert_batch` | `nomarr.persistence.collections_base` | Collection-owned upsert paths using `DOCUMENT_WRITE_UPSERT_MANY`; single-doc upsert auto-populates `match_fields` from criteria when absent |
| `BaseCollection.count` | `nomarr.persistence.collections_base` | Template-backed count via `AGGREGATION_COUNT_BY_CRITERIA`; rejects aggregate-specific fields |
| `BaseCollection.aggregate` | `nomarr.persistence.collections_base` | Template-backed aggregate via `AGGREGATION_FIELD_COUNTS`; requires `field_name` or `query_spec.aggregate_fields` |
| `_reject_mixed_query_inputs` / `_coerce_criteria` / `_serialize_criteria` / `_criteria_to_equality_filter` / `_returns_single_document` / `_bind_template` / `_execute_bound_template` | `nomarr.persistence.collections_base` | Internal helpers defining the collection-first criteria normalization, validation, singleton rules, and template execution boundary |
| `Database._COLLECTION_FIRST_ROOTS` | `nomarr.persistence.db` | Enforced root inventory: `get`, `insert`, `update`, `upsert`, `delete`, `count`, `aggregate`, `truncate` |
| `Database._assert_collection_first_surface` / `_bind_collection_instance` | `nomarr.persistence.db` | Binding-time enforcement that every static and dynamic collection exposes the normative collection-first roots |

**Tests added/updated**

- `tests/unit/persistence/test_accessors.py` — field-accessor delegation and compatibility-boundary coverage
- `tests/unit/persistence/test_collections_base.py` — collection-first execution boundary, metadata use, and collection-family behavior
- `tests/unit/persistence/database/test_db.py` — collection-surface enforcement for static and dynamic bindings
- `tests/integration/test_persistence_aql_validation.py` — live-Arango collection-first round-trip coverage with explicit skip when no database is configured

**Verification caveats**

- The collection-first live round-trip integration coverage requires a configured ArangoDB and skips explicitly when unavailable.
- `_criteria_to_equality_filter()` intentionally rejects non-EQ multi-criteria update/delete until a reviewed template is added; this is a design gate, not an accidental gap.
- Implementation evidence for Part B is present in code and tests, but the original contracts ledger entry was missing; this section records the actual implemented boundary post-crash recovery.

### Plan C (binding scope for pending implementation)

**Helpers that must be explicitly classified**

| Symbol | Current module | Required review outcome |
|------|----------------|-------------------------|
| `StateGraphCollection.transition(file_ids: list[str], from_state: str, to_state: str) -> None` | `nomarr.persistence.collections_base` | Keep only if it remains a true atomic state-graph primitive under the DD’s stricter storage-native test; otherwise replace with a normalized relationship/state mutation surface in the same plan. |
| `BaseCollection.count_inbound_connections(edge_collection: str, *, filter_field: str, filter_values: list[Any], return_field: str = "_id", label: str = "value", limit: int \| None = None, offset: int = 0) -> list[Document]` | `nomarr.persistence.collections_base` | Keep only if it is a reusable relationship-native primitive rather than a convenience helper. |
| `BaseCollection.count_outbound_connections(edge_collection: str, *, filter_field: str, filter_values: list[Any], return_field: str = "_id", label: str = "value", limit: int \| None = None, offset: int = 0) -> list[Document]` | `nomarr.persistence.collections_base` | Keep only if it is a reusable relationship-native primitive rather than a convenience helper. |
| `CollectionDelete.unreferenced(edge_collection: str) -> int` | `nomarr.persistence.accessors` | Keep only if it qualifies as a narrow storage-maintenance primitive; otherwise move above persistence or normalize into a generic reviewed capability. |
| `VectorCollection.ann_search(vector: list[float], limit: int, nprobe: int = 10, *, filter: dict[str, Any] \| None = None) -> list[Document]` | `nomarr.persistence.collections_base` | Presumptively retained as the vector-native primitive. |
| `VectorCollection.upsert_vector(file_id: str, model_suite_hash: str, embed_dim: int, vector: list[float], num_segments: int) -> None` | `nomarr.persistence.collections_base` | Reclassify as generic document write + edge orchestration unless implementation proves otherwise. |
| `VectorCollection.get_vector(file_id: str) -> Document \| None` | `nomarr.persistence.collections_base` | Reclassify unless it survives as a justified storage-native retrieval primitive. |
| `VectorCollection.get_vectors_by_file_ids(file_ids: list[str]) -> list[Document]` | `nomarr.persistence.collections_base` | Reclassify unless it survives as a justified storage-native retrieval primitive. |
| `VectorCollection.delete_by_file_id(file_id: str) -> int` / `delete_by_file_ids(file_ids: list[str]) -> int` | `nomarr.persistence.collections_base` | Reclassify as generic delete criteria or higher-layer orchestration unless implementation proves true storage-native semantics. |
| `VectorCollection.move_collection(dest: str) -> int` | `nomarr.persistence.collections_base` | Keep only if it is demonstrably single-step storage maintenance; otherwise move into higher-layer orchestration. |

**Existing higher-layer seams expected to absorb orchestration if helpers move**

| Symbol | Module | Current role |
|--------|--------|--------------|
| `transition_file_state(db: Database, file_ids: list[str], from_state: str, to_state: str) -> None` | `nomarr.components.library.library_file_state_comp` | Validation/policy wrapper around persistence transition; likely owner of non-native transition policy. |
| `get_hot_namespace(db: Database, backbone_id: str, library_key: str) -> VectorsTrackHotNamespace` | `nomarr.components.ml.vectors.ml_vector_registry_comp` | Resolves registered hot vector namespaces through `Database.register(...)`. |
| `get_cold_namespace(db: Database, backbone_id: str, library_key: str, collection_suffix: str \| None = None) -> VectorsTrackColdNamespace` | `nomarr.components.ml.vectors.ml_vector_registry_comp` | Resolves registered cold vector namespaces through `Database.register(...)`. |
| `get_maintenance_namespace(db: Database, backbone_id: str, library_key: str) -> VectorsTrackMaintenanceProtocol` | `nomarr.components.ml.vectors.ml_vector_registry_comp` | Existing maintenance seam for paired hot/cold vector collections. |
| `delete_vectors_by_file_id(db: Database, file_id: str) -> int` / `delete_vectors_by_file_ids(db: Database, file_ids: list[str]) -> int` | `nomarr.components.ml.vectors.ml_vector_registry_comp` | Existing cross-namespace vector cleanup seam; likely destination for moved delete orchestration. |

**Plan C constraints**

- `Database` remains the only public persistence entry point even when orchestration moves upward.
- Any helper kept in persistence must remain single-step, storage-shaped, and justified as generic capability, true storage-native primitive, or narrow storage maintenance.
- No Part C refactor may reintroduce module-scope constructor imports that recreate the `nomarr.persistence.base` / `constructor` partial-initialization cycle seen in prior persistence work.



### Plan C

**Final classification outcomes**

| Classification | Symbol | Module | Final outcome |
|------|--------|--------|---------------|
| Storage-native primitive | `BaseCollection.count_inbound_connections(edge_collection: str, *, filter_field: str, filter_values: list[Any], return_field: str = "_id", label: str = "value", limit: int \| None = None, offset: int = 0) -> list[Document]` | `nomarr.persistence.collections_base` | Retained as a relationship-native primitive over the constructor verb. |
| Storage-native primitive | `BaseCollection.count_outbound_connections(edge_collection: str, *, filter_field: str, filter_values: list[Any], return_field: str = "_id", label: str = "value", limit: int \| None = None, offset: int = 0) -> list[Document]` | `nomarr.persistence.collections_base` | Retained as a relationship-native primitive over the constructor verb. |
| Storage-native primitive | `CollectionDelete.unreferenced(edge_collection: str) -> int` | `nomarr.persistence.accessors` | Retained as a narrow storage-maintenance primitive that delegates to `delete_unreferenced(...)`. |
| Storage-native primitive | `VectorCollection.ann_search(vector: list[float], limit: int, nprobe: int = 10, *, filter: dict[str, Any] \| None = None) -> list[Document]` | `nomarr.persistence.collections_base` | Retained as the true vector-native ANN primitive. |
| Storage-native primitive | `EdgeCollection.replace_targets(from_ids: list[str], from_target: str, to_target: str) -> None` | `nomarr.persistence.collections_base` | Retained as the normalized relationship-native edge-target replacement primitive. |
| Compatibility shim only | `VectorCollection.upsert_vector(file_id: str, model_suite_hash: str, embed_dim: int, vector: list[float], num_segments: int) -> None` | `nomarr.persistence.collections_base` | Compatibility-only shim over collection-first `upsert(...)` plus file→vector edge maintenance for transitional callers. |
| Compatibility shim only | `VectorCollection.get_vector(file_id: str) -> Document \| None` | `nomarr.persistence.collections_base` | Compatibility-only shim over collection-first `get(query_spec=ReadQuerySpec(...))`. |
| Compatibility shim only | `VectorCollection.get_vectors_by_file_ids(file_ids: list[str]) -> list[Document]` | `nomarr.persistence.collections_base` | Compatibility-only shim over collection-first `get.in_(file_id=...)`. |
| Compatibility shim only | `StateGraphCollection.transition(file_ids: list[str], from_state: str, to_state: str) -> None` | `nomarr.persistence.collections_base` | Compatibility-only shim over `EdgeCollection.replace_targets(...)`; state validation/policy stays in components. |
| Component entry point | `upsert_hot_track_vector(db: Database, file_id: str, backbone: str, model_suite_hash: str, embed_dim: int, vector: list[float], num_segments: int, library_key: str) -> str` | `nomarr.components.ml.vectors.ml_vector_persist_comp` | Owns hot-vector write orchestration through registered collection-first surfaces (`upsert(...)` + edge upsert), not the persistence shim. |
| Component entry point | `search_similar_cold_track_vectors(db: Database, backbone_id: str, library_key: str, seed_vector: list[float], result_limit: int, vector_group_size: int, vector_search_thoroughness: int) -> list[dict[str, Any]]` | `nomarr.components.ml.vectors.ml_vector_retrieve_comp` | Owns cold-vector similarity search orchestration via collection-first `count()` plus storage-native `ann_search(...)`; the `ReadQuerySpec` retrieval seam remains `get_cold_track_vector(...)`. |

**Tests/verification updated in Phase 4**

- `tests/unit/persistence/test_accessors.py` — added `CollectionDelete.unreferenced(...)` delegation coverage.
- `tests/unit/persistence/test_collections_base.py` — added coverage for vector compatibility shims delegating to collection-first roots; existing graph count, edge-target replacement, and state-transition tests remain green.
- `tests/unit/components/ml/vectors/test_ml_vector_persist_comp.py` — strengthened coverage that hot-vector persistence uses generic collection-first `upsert(...)`, not `VectorCollection.upsert_vector(...)`.
- `tests/unit/components/ml/vectors/test_ml_vector_retrieve_comp.py` — strengthened coverage that similarity search stays ANN-native and does not fall back to `get(...)`/`ReadQuerySpec` retrieval.
- `tests/unit/components/library/test_library_file_state_comp.py` — strengthened coverage that state transitions stay on the validated component path and delegate via `db.file_states.transition(...)` rather than direct edge mutation calls.



---

### Plan D

**Final caller migration / cleanup outcomes**

| Outcome | Symbol / Rule | Status | Notes |
|------|----------------|--------|-------|
| Removed compatibility shim | `VectorCollection.delete_by_file_id(file_id: str) -> int` | removed | Deleted after caller migration; vector deletion now belongs to collection-first delete criteria or higher-layer orchestration. |
| Removed compatibility shim | `VectorCollection.delete_by_file_ids(file_ids: list[str]) -> int` | removed | Deleted with its last transitional callers; no longer exposed on `VectorCollection`. |
| Enforcement | Import-linter contract `Higher layers must not import persistence collection/accessor internals` | implemented | Keeps `Database` as the higher-layer public persistence entry point. |
| Enforcement test | `tests/test_architecture_qc.py::test_higher_layers_do_not_import_persistence_collection_or_accessor_internals` | implemented | Fails fast on direct higher-layer imports of `nomarr.persistence.collections_base` or `nomarr.persistence.accessors`. |
| Enforcement test | `tests/unit/persistence/test_persistence_enforcement.py` | implemented | Guards collection-name binding, closed collection-first roots, and reserved bespoke public helper names. |
| Retained compatibility seam | `db.file_states.transition(file_ids, from_state, to_state)` | retained | Thin delegate to `EdgeCollection.replace_targets(...)`; transition validation and policy stay in `transition_file_state(...)`. |
| Retained compatibility seam | `Database.register(collection_name, template_name)` | retained | Narrow runtime vector-registration seam; template validation and collection-first root enforcement still happen during binding. |
| Retained compatibility seam | `VectorCollection.upsert_vector(file_id, model_suite_hash, embed_dim, vector, num_segments)` | retained | Transitional thin shim over collection-first `upsert(...)` plus `file_has_vectors` edge upsert; hot-vector ingestion lives in components. |
| Retained compatibility seam | `VectorCollection.get_vector(file_id) -> Document \| None` | retained | Transitional thin shim over collection-first `get(query_spec=ReadQuerySpec(...))`; retained for transitional retrieval callers. |
| Retained compatibility seam | `VectorCollection.get_vectors_by_file_ids(file_ids)` | retained | Transitional thin shim over collection-first `get.in_(file_id=...)`. |

**Phase 5 verification**

- `lint_project_backend(check_all=True)` executed for full backend lint, import-linter, and test coverage visibility.
- `pytest tests/unit/persistence/ tests/unit/components/ml/vectors/ tests/test_architecture_qc.py tests/unit/persistence/test_persistence_enforcement.py -q` reported `461 passed, 1 skipped`.
- `pytest tests/integration/test_persistence_aql_validation.py -q` reported `1 passed, 3 skipped`.
- `lint-imports --config pyproject.toml` reported `10 kept, 0 broken`.

**Cleanup notes**

- Part C outcomes remain recorded under the proper `Plan C` section above.
- The intentionally retained compatibility seams after Part D are `db.file_states.transition(...)`, `Database.register(...)`, `VectorCollection.upsert_vector(...)`, `VectorCollection.get_vector(...)`, and `VectorCollection.get_vectors_by_file_ids(...)`.
- The vector delete compatibility shims were removed from `VectorCollection`; the ledger now records them as removed instead of retained.

**Supplementary Phase 5 blocker audit closure**

| Caller | Outcome | Notes |
|------|---------|-------|
| `nomarr/app.py` | migrated | Replaced `db.health.component_id.{upsert,update}(...)` with collection-first `db.health.{upsert,update}(component_id=..., fields=...)`. |
| `nomarr/services/infrastructure/worker_system_svc.py` | migrated | Replaced `worker_restart_policy.component_id.{get,update,upsert}(...)` and `meta.key.{get,upsert}(...)` with collection-first roots. |
| `nomarr/services/infrastructure/workers/discovery_worker.py` | migrated | Replaced `db.health.component_id.{upsert,update}(...)` with collection-first health operations. |
| `nomarr/services/infrastructure/keys_svc.py` | migrated | Replaced `meta.key.*`, `sessions.session_id.delete(...)`, and `sessions.expiry_timestamp.get.{lte,gte}(...)` with collection-first `get`/`upsert`/`delete` roots. |
| `nomarr/services/infrastructure/info_svc.py` | migrated | Replaced `db.meta.key.get("gpu_resources")` with collection-first `db.meta.get(key=...)`. |
| `nomarr/services/infrastructure/health_monitor_svc.py` | migrated | Replaced `db.health.component_id.upsert(...)` with collection-first `db.health.upsert(component_id=..., fields=...)`. |
| `nomarr/services/domain/tagging_svc/write.py` | migrated | Replaced `db.meta.key.get("calibration_version")` with collection-first `db.meta.get(key=...)`. |
| `nomarr/components/ml/vectors/ml_vector_registry_comp.py` | approved seam + migrated cleanup callers | `Database.register(...)` remains the Phase 1-approved narrow runtime vector-registration seam. The additional field-accessor delete callers in this file were migrated to collection-first `delete(...)` / `delete.in_(...)` roots. |
| `nomarr/components/library/library_admin_comp.py` | migrated | Replaced `*.library_key.delete(...)` document cleanup calls with collection-first `delete(library_key=...)`. Relationship traversal/deletion helpers in the file remain collection-owned primitives, not field-accessor debt. |

- No caller from the supplementary Phase 5 blocker list remains ambiguous: each path is now either migrated to collection-first operations or explicitly covered by the approved `Database.register(...)` compatibility seam.
- Additional acknowledged legacy debt from this supplementary audit: none.

---

## Decisions Log

| Plan | Decision | Reason |
|------|----------|--------|
| A | Capability families, query specs, template assets, and surface API remain explicitly separated in the foundation modules. | Prevents the old overloaded-verb model from reappearing under a new name. |
| A | Naming grammar enforcement lives in the Part A foundation instead of being deferred to later cleanup. | Prevents new bespoke generic helper names from proliferating during migration. |
| A | Metadata bridge methods on `BaseCollection` / `FieldAccessor` are underscore-prefixed internal helpers only. | Lets validation/template code inspect legacy structures without re-legitimizing field-first APIs as the target architecture. |
| B | Generic collection behavior is now collection-owned and field accessors are frozen compatibility shims. | Makes `db.<collection>` the normative persistence surface while preventing silent drift back to field-first architectural ownership. |
| B | Binding-time enforcement in `Database` requires every collection to expose the closed collection-first root inventory. | Prevents future collection classes or runtime-registered collections from bypassing the normalized capability surface. |
| B | Multi-criterion update/delete remains EQ-only until a reviewed template exists for broader semantics. | Preserves the DD rule that unsupported query shapes must fail explicitly rather than bypass validation with ad hoc AQL. |
| D | The surviving persistence-specific surface is limited to true storage-native primitives and compatibility shims with explicit transitional intent. | Records the shipped classification outcome from Phase 4 so future work does not mistake vector-branded compatibility helpers for normative architecture. |
| D | Hot vector writes and cold similarity search orchestration live in components, while persistence keeps only collection-first roots plus storage-native ANN/graph maintenance verbs. | Preserves the collection-first boundary and keeps multi-step orchestration above persistence without breaking transitional callers. |
