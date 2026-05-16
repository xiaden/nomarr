# Persistence Tier 3 Intent API Refactor — Design Document

**Status:** Draft  
**Author:** GitHub Copilot  
**Created:** 2026-05-14  

**Related Documents:**

- [ADR-031: AQL Primitives and Intent Sub-Facades as Canonical Persistence Architecture](../decisions/ADR-031-aql-primitives-and-intent-sub-facades-as-canonical-persistence-architecture.md) — Governing architecture decision
- [DD: Persistence Layer Consolidation: AQL Primitives + Intent Facade](./DD-persistence-aql-primitives-intent-facade.md) — Parent architecture DD this refactor refines
- [DD: Persistence Tier 2 Domain Capability Bindings Refactor](./DD-persistence-tier2-domain-capability-bindings-refactor.md) — Tier 2 internal capability contract that backs this public API cleanup
- [DD: Persistence Tier 1 AQL Primitives Refactor](./DD-persistence-tier1-aql-primitives-refactor.md) — Tier 1 primitive contract that constrains how Tier 2 implements shared query shapes
- [ADR-004: Schema Refactor V1 — Graph Normalization and Collection Decomposition](../decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Preserved storage model constraints
- [TASK-PERSIST01 Contracts Ledger](../../plans/pending/TASK-PERSIST01/TASK-PERSIST01-CONTRACTS.md) — Historical migration contract ledger; not the long-term source of truth for public API shape

---

## Scope

`nomarr/persistence/api/**`, `nomarr/persistence/db.py`, and all caller-facing persistence usage in `nomarr/components/**`, `nomarr/services/**`, and `nomarr/workflows/**`.

This DD covers the **Tier 3 public API refactor only**. Tier 1 primitives and Tier 2 AQL bindings remain the implementation mechanism; schema shape and collection layout do not change.

---

## Problem Statement

`ADR-031` already established the correct architecture: callers interact only through `db.library`, `db.app`, and `db.ml`, while persistence hides AQL and storage choreography internally.

The current codebase only partially satisfies that decision.

Today, the Tier 3 sub-facades are a mix of:

1. **Real public intent methods** — e.g. `list_files_in_state`, `replace_file_states`, `search_vectors`
2. **Storage-shaped pass-through methods** — e.g. edge upserts, link mutations, low-level batch helpers, collection truncates
3. **Incomplete intent surfaces** that force callers to perform follow-up choreography themselves

This leaves the public API feeling like a lightly wrapped graph toolkit rather than an application API.

Concrete leak examples in the current code:

- `nomarr/components/library/library_file_mutation_comp.py` composes file deletion and reconciliation from low-level operations like `delete_all_file_links_for_library`, `upsert_library_file_links_batch`, `link_file_to_library`, `delete_file`, and `delete_file_state_edges`
- `nomarr/components/tagging/tag_write_comp.py` manipulates raw tag-edge methods such as `get_song_tag_edges_for_tags`, `insert_song_tag_edges`, `upsert_song_tag_edge`, and `delete_song_tag_edge_by_id`
- `nomarr/components/library/scan_lifecycle_comp.py` combines scan-record and scan-edge methods instead of invoking a single scan lifecycle intent
- `nomarr/components/ml/vectors/ml_vector_persist_comp.py` and `ml_vector_registry_comp.py` still manage file/vector edge persistence explicitly through `upsert_file_has_vector_edge` and `delete_file_has_vector_edges_*`
- `nomarr/components/library/library_file_query_comp.py` and related query helpers still rely on low-level list/filter/edge/truncate methods that reflect storage layout rather than caller intent

The result is architectural drift:

- call sites still know too much about graph edges and storage layout
- Tier 3 surface area is large but not authoritative
- method naming is inconsistent across intent methods, low-level mechanics, and maintenance operations
- documentation and contract ledgers have already drifted from implementation once, which increases the chance of future re-leaks

Navidrome is a special case within that drift. Nomarr no longer owns plugin-facing Navidrome mediafile-ID resolution or backend-managed playlist output contracts. Plugin-backed flows are descriptor-based, and Navidrome-side identity/play retrieval now belongs on the plugin side rather than in Nomarr persistence.

---

## Non-Goals

This refactor does **not**:

- change ArangoDB schema, collection names, or edge model
- collapse normalized graph relationships back into embedded documents
- replace the three-facade split (`db.library`, `db.app`, `db.ml`)
- move business workflows into services or persistence indiscriminately
- expose raw `db.db` operations as the main caller path
- redesign Tier 1 primitives beyond what is needed to support new Tier 3 intent methods

---

## Architecture

## Core Decision

Tier 3 is refactored into a **complete caller-facing intent API**.

A caller should be able to say:

- “add this file to this library”
- “replace these file tags”
- “add or update this scan”
- “replace vectors for this file”
- “replace this model output”
- “update this config option”

and then stop.

Tier 3 methods must own all required persistence choreography:

- document insert/update/upsert
- `_id` / `_key` normalization
- edge maintenance
- state initialization or cleanup
- deduplication and orphan handling where the operation requires it
- any other collection-spanning work necessary to make the requested intent true in the database

Callers must no longer stitch together several public persistence methods to complete one logical persistence action.

### Public API rules

1. **Top-level Tier 3 methods describe caller intent.**
2. **Tier 3 may cross collection boundaries internally without exposing that fact to callers.**
3. **Raw edge, link, and plumbing methods are not default public API.**
4. **Administrative and destructive reset operations must be explicitly isolated as maintenance-only operations.**
5. **If a caller routinely needs two or more persistence calls to complete one write intent, the public API is incomplete.**

### Maintenance surface

Maintenance-only operations remain inside the three-facade model, but they do **not** stay on the routine top-level method surface.

The target shape is:

- `db.library.maintenance.*`
- `db.app.maintenance.*`
- `db.ml.maintenance.*`

These nested maintenance surfaces are for:

- admin workflows
- diagnostics
- migration/bootstrap code
- destructive resets and explicit repair tooling

Routine components, services, and workflows should not call them during normal feature behavior.

This resolves the maintenance-surface question for this refactor. A separate top-level `db.admin` is **not** introduced.

### Method taxonomy for this refactor

Every current Tier 3 method falls into one of four buckets:

| Bucket | Meaning | Target state |
| --- | --- | --- |
| **Keep public** | Already expresses a stable caller-facing intent or query | Stays public, possibly renamed for consistency |
| **Promote / replace** | Public but too thin or too low-level to be the final contract | Replaced by a richer intent method |
| **Internalize** | Storage-shaped plumbing that belongs in Tier 2 or a private Tier 3 helper | Removed from caller-facing public API |
| **Maintenance-only** | Destructive/reset/admin operations not meant for routine app flows | Moved behind an explicit maintenance/admin surface |

### Naming rules

Use a small stable verb set:

- `add_*` — create a new logical entity or perform a create-oriented intent
- `get_*` — fetch one by identity or unique selector
- `list_*` — fetch many with stable list semantics
- `find_*` — lookup when absence or scope search is central to the method
- `update_*` — partial update of an existing logical entity
- `replace_*` — overwrite a logical child set or relationship set
- `remove_*` — cascading or logical delete of an entity/relationship set
- `count_*` — counts only
- `search_*` — fuzzy/pattern/query search

Reserved for maintenance surfaces only:

- `truncate_*`
- raw `insert_*_edge`, `upsert_*_edge`, `delete_*_edge`
- raw `link_*`, `unlink_*`

### Atomicity and consistency contract

Promoted Tier 3 intent methods must provide a single logical write contract.

- A caller may assume that one Tier 3 intent method either fully applies its required persistence side effects or reports failure without leaving partially completed caller-visible state for that logical entity.
- Tier 2 achieves this by using one handwritten AQL operation, one explicit transaction, or another persistence-local implementation that preserves all-or-nothing semantics for the touched logical entity.
- Maintenance methods may be best-effort when their purpose is destructive reset or repair; routine intent methods may not be best-effort.
- If full all-or-nothing semantics are impossible for a specific operation, that exception must be documented on the method contract before implementation.

### Source of truth

After this DD is accepted, the authoritative public contract is:

1. `ADR-031`
2. this DD
3. the live code in `nomarr/persistence/api/`

`TASK-PERSIST01-CONTRACTS.md` remains historical migration context, not the long-term authority for Tier 3 surface design.

During migration, newly added methods and changed public contracts follow this DD even while legacy methods still exist temporarily for unmigrated callers. Transitional legacy methods are compatibility shims, not precedent for future API shape.

### Promote-to-internalize sequencing rule

Some current methods appear in both **Promote / replace** and **Internalize** logic. That is intentional.

- First, add the richer replacement method.
- Next, migrate callers.
- Finally, internalize or remove the older thin method.

No method listed as a promotion target should remain a routine caller-facing method after its replacement is adopted.

---

## Refactor Plan by Sub-Facade

## `db.library`

### Keep public

These are already close to caller intent and should remain public with only light naming cleanup if needed:

- `add_library`
- `get_library`
- `get_library_by_name`
- `list_libraries`
- `list_library_keys`
- `update_library`
- `remove_library` (preferred public delete path)
- `get_file`
- `get_file_by_path`
- `get_file_by_path_unscoped` (rename candidate: `find_file_by_path_any_library`)
- `list_files_by_ids`
- `list_files`
- `list_library_files`
- `list_library_file_ids`
- `find_library_file_by_chromaprint`
- `search_files_by_text`
- `search_files_by_tag`
- `count_files`
- `count_files_by_tag`
- `count_recently_tagged`
- `list_tracks_for_matching`
- `get_tag`
- `list_tags_for_file`
- `list_tags`
- `count_tags`
- `list_all_tag_names`
- `list_tags_by_name`
- `list_genre_tags_for_files`
- `list_folders_for_library`
- `get_folder`

### Promote / replace with richer intent methods

These methods expose only one storage step of a larger caller intent and should be replaced by richer operations:

| Current method(s) | Problem | Target public method |
| --- | --- | --- |
| `add_file`, `update_file`, `upsert_file`, `upsert_files_batch`, `upsert_files_for_library`, `link_file_to_library`, `upsert_library_file_links_batch`, `delete_all_file_links_for_library` | Callers still orchestrate file doc persistence, library linking, and follow-up state work themselves | `add_file_to_library(library_id: str, payload: dict) -> str`; `add_files_to_library(library_id: str, payloads: list[dict]) -> list[str]`; `update_library_files(library_id: str, payloads: list[dict], *, remove_missing: bool) -> dict[str, int]`; `update_library_file_path(file_id: str, new_path: str) -> None` |
| `delete_file` | Too low-level for real caller intent; callers still release claims and clean side-effects separately | `remove_file(file_id: str) -> None`; `remove_file_by_path(path: str, library_id: str | None = None) -> None` |
| `add_tag`, `upsert_tag`, `find_or_create_tag`, `delete_tag`, `delete_all_tags_for_file`, `get_tags_for_files_batch` | Callers still manage tag replacement, merge, relink, and cleanup choreography | `replace_file_tags(file_id: str, tags: list[dict]) -> None`; `replace_tag_references(source_tag_id: str, target_tag_id: str) -> None`; `replace_selected_tag_references(file_ids: list[str], source_tag_id: str, target_tag_id: str) -> None`; `remove_file_tags(file_id: str, tag_keys: list[str] | None = None) -> None`; `list_file_tags_for_files(file_ids: list[str], *, name_starts_with: str | None = None) -> dict[str, list[dict]]` |
| `get_library_ids_for_files` | Mainly used by callers compensating for incomplete file/library intents | `list_files_with_library_ids(file_ids: list[str]) -> list[dict]` or an equivalent enriched `list_files_by_ids(...)` contract |
| `add_folder`, `delete_folder`, `link_folder_to_library`, `delete_folder_link` | Exposes folder graph mechanics rather than folder lifecycle intent | `add_library_folder(library_id: str, payload: dict) -> str`; `remove_library_folder(library_id: str, folder_id: str) -> None`; `replace_library_folders(library_id: str, payloads: list[dict]) -> None` |
| `get_artist_album_frequencies` | Analytics intent is real, but current method is hard-coded and too narrow | `list_tag_value_frequencies(tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]` |

### Internalize

The following leak storage or graph mechanics and should no longer be general public Tier 3 methods:

- `get_song_tag_edges_for_tags`
- `insert_song_tag_edges`
- `delete_song_tag_edge_by_id`
- `upsert_song_tag_edge`
- `delete_song_tag_edges_for_file`
- `count_song_tag_edges`
- `count_song_tag_edges_for_file_state`
- `upsert_file_links_batch`
- `link_file_to_library`
- `delete_files_for_library`
- `delete_folders_for_library`
- `delete_all_folder_links_for_library`
- `delete_folder_link`
- `count_library_file_links`
- `aggregate_tag_field`

### Maintenance-only

These methods are valid operationally but should not remain casual caller-facing API:

- `truncate_files`
- `truncate_file_links`
- `truncate_folder_links`
- `truncate_folders`
- `truncate_tags`
- `truncate_song_tag_edges`
- `list_orphaned_file_ids`
- `list_orphaned_tag_ids`
- `delete_tags_by_ids`

If retained, they should move behind an explicit maintenance/admin surface, not the routine `LibraryDb` caller contract.

#### Library method semantics notes

- `update_library_files(...)` is the canonical bulk sync intent for a library scan or repair pass. It owns upsert, link creation, state initialization for new files, and optional removal of no-longer-present files. It returns summary counters such as inserted, updated, retained, and removed.
- `replace_tag_references(...)` means move all file associations from the source tag to the target tag and delete the source tag if it becomes orphaned.
- `replace_selected_tag_references(...)` means retarget only the selected file/tag relationships without implying full source-tag deletion semantics. It exists for tag-curation flows where the source tag remains valid for other files.

---

## `db.app`

### Keep public

These are valid app-level contracts and should remain public after direct naming normalization where needed:

- `get_file_state`
- `list_files_in_state`
- `list_file_docs_in_state`
- `count_files_in_state`
- `get_lock`
- `add_lock`
- `remove_lock`
- `list_locks`
- `list_claims`
- `count_claims`
- `get_health`
- `count_healthy`
- `list_worker_health`
- `list_migrations`
- `list_vram_promises`
- `count_vram_promises`

### Promote / replace with richer intent methods

| Current method(s) | Problem | Target public method |
| --- | --- | --- |
| `transition_file_states`, `add_file_state_edge`, `delete_file_state_edges` | File-state writes still mix graph details with non-canonical verbs | `add_file_states(file_ids: list[str], state: str) -> None`; `replace_file_states(file_ids: list[str], state: str) -> None`; `remove_file_states(file_ids: list[str]) -> None` |
| `get_scan_record`, `add_scan_record`, `update_scan_record`, `delete_scan_record`, `upsert_library_scan_edge`, `delete_library_scan_edge` | Scan lifecycle is split across doc and edge methods, forcing caller choreography | `add_scan(library_id: str, payload: dict) -> None`; `update_scan(library_id: str, fields: dict) -> None`; `remove_scan(library_id: str) -> None` |
| `upsert_pipeline_state`, `update_pipeline_state`, `delete_pipeline_state`, `delete_pipeline_state_edges_for_library`, `get_pipeline_state_doc` | Pipeline state remains storage-shaped | `update_pipeline_state(library_id: str, state: str) -> None`; `remove_pipeline_state(library_id: str) -> None`; `get_pipeline_state(library_id: str) -> str | None` |
| `acquire_lock`, `release_lock`, `insert_lock`, `upsert_lock` | Lock persistence currently mixes non-canonical verbs with storage mechanics | `add_lock(payload: dict) -> str`; `remove_lock(lock_id: str) -> None` |
| `claim_file`, `release_claim`, `insert_worker_claim`, `delete_claims_for_workers`, `delete_claims_for_files`, `steal_claim`, `aggregate_worker_claims` | Claim management still uses non-canonical verbs and storage-shaped operations | `add_claim(payload: dict) -> str`; `remove_claim(claim_id: str) -> None`; `remove_claims(*, worker_ids: list[str] | None = None, file_ids: list[str] | None = None) -> int`; retained read surface stays `list_claims(...)` / `count_claims(...)` |
| `upsert_vram_promise`, `delete_vram_promise` | Promise management is meaningful but too storage-named | `add_vram_promise(payload: dict) -> None`; `remove_vram_promise(promise_id: str) -> None` |

### Promote / split generic app persistence by actual purpose

These methods should not survive as a generic `meta` bag. They need to be renamed and split by the real domain they manage:

- `get_meta`
- `upsert_meta`
- `delete_meta`
- `list_meta_keys_by_prefix`

Target disposition:

- replace configuration-style usage with explicit config contracts such as `get_config_option(key: str)`, `list_config_options(prefix: str | None = None)`, `update_config_option(key: str, value: object)`, and `remove_config_option(key: str)`
- split non-configuration uses into purpose-specific contracts at the appropriate layer (for example: auth secrets, calibration runtime state, worker control state, or diagnostics snapshots)
- if a generic key/value store remains necessary internally, keep it below the public Tier 3 contract rather than exposing `meta` verbs to callers

### Internalize

The following should not remain general public API:

- `get_state_edges_for_files`
- `acquire_lock`
- `release_lock`
- `insert_lock`
- `upsert_lock`
- `claim_file`
- `release_claim`
- `insert_worker_claim`
- `delete_scan_record`
- `delete_scan_records_for_library`
- `add_file_state_edge`
- `delete_file_state_edges`
- `upsert_library_scan_edge`
- `delete_library_scan_edge`
- `delete_pipeline_state`
- `delete_pipeline_state_edges_for_library`

### Maintenance-only

- `truncate_file_state_edges`
- `truncate_scan_records`
- `truncate_library_scan_edges`
- `truncate_pipeline_states`
- `truncate_pipeline_state_edges`
- `truncate_health`
- `delete_all_worker_claims`
- `list_collections` (if retained, expose only as `db.app.maintenance.list_collections()` for diagnostics/bootstrap flows)

### Legacy Navidrome persistence to remove

These methods should not be promoted, renamed, or kept as public Tier 3 API. They represent the old backend-owned Navidrome-ID / play-history contract that no longer matches the plugin-era boundary:

- `get_nd_track`
- `upsert_nd_track`
- `delete_nd_tracks_for_file`
- `list_nd_track_keys`
- `bulk_upsert_nd_tracks`
- `delete_nd_tracks_cascade`
- `ensure_nd_file_link`
- `bulk_ensure_nd_file_links`
- `resolve_nd_track_to_file`
- `resolve_file_to_nd_track`
- `bulk_resolve_nd_tracks_to_files`
- `bulk_resolve_files_to_nd_ids`
- `get_nd_id_edge`
- `upsert_nd_playcount`
- `increment_nd_play`
- `bulk_upsert_nd_plays`
- `get_top_nd_plays`

Target disposition:

- remove from routine Tier 3 API
- migrate any remaining caller need to descriptor-based plugin contracts
- if temporary compatibility is required, isolate behind legacy-only code paths slated for deletion rather than future public naming cleanup

#### App method semantics notes

- `add_scan(...)` owns both scan-record creation and the library-to-scan association needed for that lifecycle.
- `update_scan(...)` updates the active scan by `library_id`, including progress and terminal status fields, rather than exposing scan-edge mechanics.
- `get_pipeline_state(...)` returns the semantic state value rather than a storage-shaped pipeline-state document.
- Navidrome mapping and play-history queries are intentionally **not** a future Tier 3 contract here. Plugin-backed descriptor flows own external Navidrome identity resolution and play retrieval.

---

## `db.ml`

### Keep public

These are already reasonable ML-facing contracts:

- `add_vector_collection`
- `list_vector_collection_names`
- `list_vector_namespaces`
- `list_output_streams_for_file`
- `list_file_vectors`
- `search_vectors`
- `get_model`
- `get_model_by_path`
- `add_model`
- `update_model`
- `remove_model`
- `list_models`
- `count_models`
- `list_models_by_ids`
- `get_model_output`
- `list_model_outputs`
- `get_tag_model_output`
- `get_calibration_state`
- `list_calibration_states`
- `list_calibration_history_snapshots`
- `count_calibration_history`

### Promote / replace with richer intent methods

| Current method(s) | Problem | Target public method |
| --- | --- | --- |
| `upsert_output_streams_batch`, `delete_output_streams_for_file` | Batch/storage naming instead of caller intent | `replace_output_streams_for_file(file_id: str, stream_payloads: list[dict]) -> None`; `remove_output_streams_for_file(file_id: str) -> None` |
| `upsert_vector`, `upsert_file_has_vector_edge`, `delete_vectors_for_file`, `delete_file_has_vector_edges_for_file`, `delete_file_has_vector_edges_for_files` | File/vector relationship persistence is still stepwise and edge-aware | `replace_file_vectors(collection_name: str, file_id: str, vector_payloads: list[dict]) -> None`; `remove_file_vectors(collection_name: str, file_id: str) -> None`; `remove_vectors_for_files(collection_name: str, file_ids: list[str]) -> None` |
| `add_model_output`, `update_model_output`, `upsert_model_output_edge`, `delete_model_output`, `delete_model_outputs_for_model` | Model output publication still split across doc and edge mechanics | `replace_model_output(model_id: str, output_key: str, payload: dict) -> str`; `remove_model_output(output_id: str) -> None`; `remove_model_outputs_for_model(model_id: str) -> list[str]` |
| `upsert_tag_model_output`, `insert_tag_model_output_edges_batch`, `update_tag_model_output_edges_batch`, `delete_tag_model_outputs_for_model`, `delete_tag_model_output_edges_for_tag`, `delete_tag_model_output_edges_for_outputs`, `count_tag_model_output_edges_for_tag` | Tag-model-output graph maintenance is currently exposed directly | `replace_tag_model_outputs(model_id: str, docs: list[dict]) -> None`; `remove_tag_model_outputs_for_model(model_id: str) -> None`; `remove_tag_model_outputs_for_tag(tag_id: str) -> None` |
| `upsert_calibration_state`, `upsert_calibration_state_doc`, `upsert_model_has_calibration_edge`, `delete_calibration_state_doc`, `delete_model_has_calibration_edge`, `get_calibration_state_doc` | Calibration publication remains mechanically split across doc and edge methods, and read-side doc semantics leak too much storage detail | `replace_calibration_state(model_id: str, key: str, payload: dict) -> None`; `remove_calibration_state(calibration_id: str) -> None`; `get_calibration_state_view(head_name: str, label: str) -> dict | None` |
| `add_calibration_history`, `delete_calibration_history_for_model`, `delete_calibration_history_entries` | History operations are meaningful but still storage-shaped | `add_calibration_history(payload: dict) -> str`; `remove_calibration_history_for_model(model_id: str) -> None`; `remove_calibration_history_entries(entry_ids: list[str]) -> None` |

### Internalize

- `upsert_file_has_vector_edge`
- `delete_file_has_vector_edges_for_file`
- `delete_file_has_vector_edges_for_files`
- `upsert_model_output_edge`
- `get_tag_model_output_edges_for_tags`
- `insert_tag_model_output_edges_batch`
- `update_tag_model_output_edges_batch`
- `get_model_has_calibration_edges_by_ids`
- `upsert_model_has_calibration_edge`
- `delete_model_has_calibration_edge`

#### ML method semantics notes

- `replace_file_vectors(...)` owns both vector document persistence and the file-to-vector relationship updates required by the collection.
- `replace_model_output(...)` owns the output document lifecycle and its model association.
- `replace_calibration_state(...)` owns the calibration doc lifecycle and model association; the caller does not manage calibration edges directly.
- `get_calibration_state(model_id)` remains the model-level lookup. `get_calibration_state_view(head_name, label)` replaces the storage-shaped read of calibration docs by head/label identity.

### Maintenance-only

- `truncate_vector_collection`
- `truncate_vector_edges`
- `truncate_calibration_states`
- `truncate_calibration_history`

---

## Migration Strategy

### Phase 1 — Add intent-complete methods

Introduce richer Tier 3 methods without immediately deleting the old thin methods.

Priority order:

1. `db.library` file lifecycle and tag lifecycle methods
2. `db.app` scan lifecycle and state lifecycle methods
3. `db.ml` vector/model-output/calibration publication methods
4. explicit maintenance surface extraction

### Phase 2 — Migrate callers

Move current caller choreography behind the new API.

Priority migrations:

- `components/library/library_file_mutation_comp.py`
- `components/library/scan_lifecycle_comp.py`
- `components/tagging/tag_write_comp.py`
- `components/library/library_file_query_comp.py`
- `components/ml/vectors/*`
- `components/ml/onnx/tag_model_output_comp.py`
- `components/ml/calibration/*`

### Phase 3 — Delete leaked public mechanics

After callers migrate, remove or quarantine public methods in the **Internalize** and **Maintenance-only** buckets.

### Compatibility rule

During migration, do **not** accept a caller that uses a new Tier 3 intent method and still needs a second low-level Tier 3 follow-up call to finish the same persistence action. That means the new method is still too thin.

When a method is replaced, the older low-level public method may remain temporarily for backwards-compatible migration only. New code must target the promoted method immediately.

---

## Validation

This refactor is correct when all of the following are true:

1. Routine caller code no longer invokes raw edge-manipulation methods from `db.library`, `db.app`, or `db.ml`
2. Routine caller code no longer invokes `truncate_*` methods except from explicit maintenance/admin flows
3. File add/remove, tag replacement/reference updates, scan lifecycle, vector persistence, model-output publication, and calibration publication each have a single caller-facing Tier 3 entry point
4. `ADR-031` remains satisfied: callers use only `db.library`, `db.app`, and `db.ml`
5. Tier 2 owns all collection and edge choreography for the promoted intents
6. Maintenance-only operations are reachable only from `.maintenance` sub-surfaces or direct diagnostics infrastructure
7. Navidrome-ID mapping and top-play retrieval are no longer represented as future public Tier 3 API; plugin-era descriptor boundaries own those concerns

Recommended validation passes:

- targeted grep for methods in the **Internalize** bucket across `nomarr/components/**`, `nomarr/services/**`, and `nomarr/workflows/**`
- backend lint/type checks after each migration phase
- unit tests for new Tier 3 methods asserting they perform the full required side effects
- regression tests for caller sites previously known to orchestrate several persistence calls manually

---

## Risks

- **Over-thin replacement methods.** A renamed wrapper is not a refactor; promoted methods must absorb the choreography.
- **Contract drift.** This DD must remain the public-shape source of truth while the refactor is active.
- **Maintenance leakage.** Reset/truncate helpers are useful, but if they remain adjacent to routine caller methods they will keep reappearing in application code.
- **False completeness.** A facade with many methods is not necessarily complete; the criterion is whether callers can complete one persistence intent in one API call.

---

## Open Questions

1. Should `get_file_by_path_unscoped` remain public as a caller query convenience, or be replaced by a more explicit `find_file_by_path_any_library` method to avoid leaking storage scope semantics?
2. Should query-heavy helper families remain on the main Tier 3 facades for now, or be extracted into explicit query namespaces in a future follow-up once the write-surface cleanup is complete?

---

## Completion Criteria

This refactor is complete when:

- the public persistence API reads like an application API
- new Tier 3 methods own multi-collection persistence choreography
- raw edge and link methods are no longer used by routine caller code
- destructive reset operations are clearly separated from routine flows
- the live code and this DD agree on what the public contract is

---
