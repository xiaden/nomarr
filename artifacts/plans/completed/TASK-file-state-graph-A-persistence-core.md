# Task: File State Graph — Persistence Core Rewrite

## Problem Statement

The current `file_states_aql.py` uses payload-bearing state edges (`version`, `hash`, `mode`, `tagged_at`, `calibrated_at`, `written_at`, `has_namespace`) and UPSERT semantics. This creates three problems: (1) expensive full-scan subqueries for discovery ("find untagged files"), (2) state edges that conflate boolean reachability with domain data, and (3) no negative state vertices, so absence-of-edge queries require scanning the entire `library_files` collection. The design doc (`DD-file-state-graph-completion.md`) specifies a pure-boolean axis model with negative state vertices enabling O(1) INBOUND traversal discovery. This plan rewrites `FileStatesOperations` to the new model and updates bootstrap to seed all 16 vertices.

**Prerequisite:** None (Part A has no dependencies)

## Phases

### Phase 1: Define vertex constants and transition helper
- [x] Replace the three existing module-level constants (`_STATE_ML_TAGGED`, `_STATE_CALIBRATED`, `_STATE_RECONCILED`) with 16 named constants covering all 8 axes (positive + negative), plus an `ALL_STATE_VERTICES` tuple for bootstrap and migration use
    **executor:** Replaced 3 old private constants with 16 public STATE_* constants and ALL_STATE_VERTICES tuple. Kept _EDGE_COLLECTION private. Old methods have expected F821 errors until Phase 5.
  **Notes:** Constants use the format `STATE_TAGGED = "file_states/tagged"`, `STATE_NOT_TAGGED = "file_states/not_tagged"`, etc. The full list of axes is: tagged/not_tagged, too_short/not_too_short, calibrated/not_calibrated, tags_written/tags_not_written, tags_current/tags_stale, scanned/not_scanned, vectors_extracted/not_vectors_extracted, errored/not_errored. Constants are module-level (not prefixed with underscore) so migration and other modules can import them. Keep `_EDGE_COLLECTION = "file_has_state"` as private.
- [x] Add a module-level `AXIS_PAIRS` dict mapping axis name to `(positive_vertex, negative_vertex)` tuple for programmatic iteration
    **executor:** Added AXIS_PAIRS dict mapping 8 axis names to (positive, negative) vertex tuples between ALL_STATE_VERTICES and the class.
  **Notes:** Structure: `AXIS_PAIRS: dict[str, tuple[str, str]] = {"tagged": (STATE_TAGGED, STATE_NOT_TAGGED), "too_short": (STATE_TOO_SHORT, STATE_NOT_TOO_SHORT), ...}`. Used by `initialize_file_states` and bulk operations.
- [x] Implement `_transition_state(self, file_id: str, axis: str, to_positive: bool) -> None` as a private method on `FileStatesOperations` using REMOVE + INSERT AQL pattern
    **executor:** Added _transition_state as first method after __init__. Uses REMOVE+INSERT AQL with LET bindings per design doc. Resolves vertices from AXIS_PAIRS[axis].
  **Notes:** The AQL finds the existing edge for the axis (matching either positive or negative vertex), removes it, then inserts the new edge. Uses a single AQL statement with LET bindings. Bind vars: `file_id`, `positive` vertex, `negative` vertex, `new_state` (chosen by `to_positive`). The AQL pattern from the design doc: `LET old = FIRST(FOR e IN file_has_state FILTER e._from == @file_id AND (e._to == @positive OR e._to == @negative) RETURN e)` then `LET _ = old != null ? (REMOVE old._key IN file_has_state) : null` then `INSERT { _from: @file_id, _to: @new_state } INTO file_has_state`. Uses `AXIS_PAIRS[axis]` to resolve vertex names.

### Phase 2: Implement axis setter methods
- [x] Implement all 8 positive setters: `set_tagged`, `set_too_short`, `set_calibrated`, `set_tags_written`, `set_tags_current`, `set_scanned`, `set_vectors_extracted`, `set_errored` — each a one-liner calling `_transition_state(file_id, axis, to_positive=True)`
    **executor:** Added 8 positive setters (set_tagged, set_too_short, set_calibrated, set_tags_written, set_tags_current, set_scanned, set_vectors_extracted, set_errored) after _transition_state, before old methods. Note: set_calibrated redefines the old method (F811) — resolved when Phase 5 removes old methods.
  **Notes:** Signatures are all `(self, file_id: str) -> None`. No payload parameters — these are pure boolean transitions. Example: `def set_tagged(self, file_id: str) -> None: self._transition_state(file_id, "tagged", to_positive=True)`.
- [x] Implement all 8 negative setters: `set_not_tagged`, `set_not_too_short`, `set_not_calibrated`, `set_tags_not_written`, `set_tags_stale`, `set_not_scanned`, `set_not_vectors_extracted`, `set_not_errored` — each calling `_transition_state(file_id, axis, to_positive=False)`
    **executor:** Added 8 negative setters (set_not_tagged, set_not_too_short, set_not_calibrated, set_tags_not_written, set_tags_stale, set_not_scanned, set_not_vectors_extracted, set_not_errored). set_tags_stale uses axis "tags_current" with to_positive=False. set_tags_not_written uses axis "tags_written" with to_positive=False. No new lint errors in Phase 2 scope.
  **Notes:** Same pattern as positive setters. `set_tags_stale` calls `_transition_state(file_id, "tags_current", to_positive=False)` — the axis name is `tags_current`, the negative vertex is `tags_stale`.

### Phase 3: Implement bulk transitions and initialization
- [x] Implement `bulk_set_not_calibrated(self) -> int` that transitions ALL files from `calibrated` to `not_calibrated` in a single AQL query and returns the count of edges affected
    **executor:** Added bulk_set_not_calibrated() using REMOVE+INSERT AQL pattern with STATE_CALIBRATED/STATE_NOT_CALIBRATED bind vars. Returns count via len(list(cursor)).
  **Notes:** AQL: `FOR e IN file_has_state FILTER e._to == @calibrated LET r = (REMOVE e._key IN file_has_state RETURN 1) INSERT { _from: e._from, _to: @not_calibrated } INTO file_has_state RETURN 1`. Count via `LENGTH(cursor)` or cursor stats. This replaces `clear_all_calibrated()`.
- [x] Implement `bulk_set_tags_stale(self, library_id: str | None = None) -> int` that transitions files from `tags_current` to `tags_stale`, optionally scoped to a library via set intersection
    **executor:** Added bulk_set_tags_stale(library_id=None) with two AQL branches: library-scoped uses OUTBOUND traversal for set intersection, global transitions all tags_current edges. Returns count.
  **Notes:** When `library_id` is None, transitions all files. When scoped, uses: `LET lib_file_ids = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id) FOR e IN file_has_state FILTER e._to == @tags_current AND e._from IN lib_file_ids ...`. Returns count of transitions.
- [x] Implement `initialize_file_states(self, file_id: str) -> None` that creates all-negative edges for a new file (one edge per axis, all pointing to negative vertices)
    **executor:** Added initialize_file_states(file_id) that inserts one edge per axis pointing to the negative vertex. Uses AXIS_PAIRS.values() to collect negative states.
  **Notes:** Iterates `AXIS_PAIRS` and inserts 8 edges. Uses a single AQL with a `FOR axis IN @axes` pattern: bind `axes` as list of negative vertex IDs, then `FOR state IN @negative_states INSERT { _from: @file_id, _to: state } INTO file_has_state`. This is called when a new file is first upserted.
- [x] Implement `initialize_file_states_batch(self, file_ids: list[str]) -> None` that creates all-negative edges for multiple new files in a single AQL query
    **executor:** Added initialize_file_states_batch(file_ids) with nested FOR loops and ignoreErrors:true for idempotency. Early return on empty list.
  **Notes:** AQL: `FOR file_id IN @file_ids FOR state IN @negative_states INSERT { _from: file_id, _to: state } INTO file_has_state OPTIONS { ignoreErrors: true }`. The `ignoreErrors` handles the case where some files may already have edges (idempotent).

### Phase 4: Implement discovery queries
- [x] Implement `discover_next_untagged_file(self, library_id: str | None = None, exclude_claimed: bool = True) -> dict[str, Any] | None` using INBOUND traversal on `not_tagged` vertex with optional library scoping, too_short exclusion, and claim exclusion
    **executor:** Added discover_next_untagged_file with INBOUND traversal on STATE_NOT_TAGGED, too_short exclusion via set difference, optional library scoping, and optional claim exclusion. Dynamic query building with bind_vars.
  **Notes:** Base pattern: `FOR file IN INBOUND @not_tagged file_has_state`. **Must exclude too_short files** via set difference: `LET too_short_ids = (FOR f IN INBOUND @too_short file_has_state RETURN f._id)` then `FILTER file._id NOT IN too_short_ids`. Library scoping uses set intersection: `LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)` then `FILTER file._id IN lib_files`. Claim exclusion: `FILTER LENGTH(FOR c IN worker_claims FILTER c.file_id == file._id AND c.status == "active" RETURN 1) == 0`. Returns `LIMIT 1 RETURN file` or `None`. Replaces current `discover_next_untagged_file` which uses absence-of-edge scan.
- [x] Implement `get_untagged_file_ids(self, library_id: str | None = None, limit: int = 100) -> list[str]` using INBOUND traversal on `not_tagged` vertex
    **executor:** Added get_untagged_file_ids with INBOUND traversal on STATE_NOT_TAGGED, optional library scoping, SORT/LIMIT pattern. Returns list[str].
  **Notes:** Same base as above but returns `file._id` list with limit. Library scoping via set intersection.
- [x] Implement `count_untagged_files(self, library_id: str | None = None) -> int` using INBOUND traversal on `not_tagged` vertex
    **executor:** Added count_untagged_files with library_id: str | None signature (changed from old int | None). Uses LENGTH(subquery) pattern with optional library scoping.
  **Notes:** Uses `RETURN LENGTH(FOR f IN INBOUND @not_tagged file_has_state ... RETURN 1)` pattern. Library scoping via filtered traversal or intersection.
- [x] Implement `count_uncalibrated_files(self) -> int` using INBOUND traversal on `not_calibrated` vertex
    **executor:** Added count_uncalibrated_files() using RETURN LENGTH(INBOUND @not_calibrated) single-query pattern.
- [x] Implement `get_uncalibrated_tagged_file_ids(self, library_id: str) -> list[str]` using set intersection of INBOUND `file_states/tagged` and INBOUND `file_states/not_calibrated`
    **executor:** Added get_uncalibrated_tagged_file_ids(library_id) using INTERSECTION(tagged, uncalibrated) with DOCUMENT(id) filter for library scoping. library_id is the full _id string.
  **Notes:** New method replacing semantic of removed `get_tagged_paths_needing_calibration`. AQL: `LET tagged = (FOR f IN INBOUND @tagged file_has_state RETURN f._id) LET uncalibrated = (FOR f IN INBOUND @not_calibrated file_has_state RETURN f._id) FOR id IN INTERSECTION(tagged, uncalibrated) LET lib_file = DOCUMENT(id) FILTER lib_file != null AND lib_file.library_id == @library_id RETURN id`. Bind vars: `@tagged = STATE_TAGGED`, `@not_calibrated = STATE_NOT_CALIBRATED`, `@library_id`. Called by `library_svc/query.py` (Plan D caller migration).
- [x] Implement `get_stale_file_ids(self, library_id: str | None = None) -> list[str]` using INBOUND traversal on `tags_stale` vertex with optional library scoping
    **executor:** Added get_stale_file_ids(library_id=None) using INBOUND traversal on STATE_TAGS_STALE with optional library scoping via lib_files set intersection.
  **Notes:** New method — no predecessor in current code. Used by reconciliation to find files needing tag rewrite.

### Phase 5: Retain, adapt, or remove existing methods
- [x] Remove old payload-bearing methods: `set_ml_tagged`, `clear_ml_tagged`, `is_ml_tagged`, `get_ml_tagged`, `set_calibrated` (old signature with hash), `set_calibrated_batch`, `clear_calibrated`, `clear_all_calibrated`, `set_reconciled`, `clear_reconciled`, `get_files_needing_reconciliation`, `count_files_needing_reconciliation`, `get_tagged_paths_needing_calibration`, `count_recently_tagged`, `_log_tagging_diagnostics`
    **executor:** Removed all 15 old payload-bearing methods plus 3 old discovery methods. Removed logging/now_ms imports and logger instance.
  **Warning:** This is a destructive rewrite. All callers will break until Part C and Part D migrate them. The old methods are incompatible with the new model — wrapping is not feasible.
- [x] Keep `clear_all_states(self, file_id: str) -> int` and `clear_all_states_batch(self, file_ids: list[str]) -> int` unchanged — these remove all edges for a file regardless of type
    **executor:** Verified both methods exist unchanged in the new file.
- [x] Keep `get_calibration_status_by_library(self) -> list[dict[str, Any]]` — remove `calibration_hash` parameter entirely (pure-boolean edges have no hash to compare) and adapt AQL to use `STATE_CALIBRATED`/`STATE_NOT_CALIBRATED` INBOUND counts per library. Returns `[{"library_id": ..., "calibrated_count": ..., "not_calibrated_count": ...}]`. Plan D callers (`ml_calibration_state_comp.py`, `tagging_svc.py`) will drop the hash argument
    **executor:** Replaced with new signature (self) -> list[dict[str, Any]] and INBOUND counts AQL per the plan spec.
- [x] Keep `library_has_tagged_files(self, library_id: str) -> bool` but update its AQL to use `STATE_TAGGED` constant instead of `_STATE_ML_TAGGED`
    **executor:** Updated bind var to use STATE_TAGGED. Same AQL structure and signature.
- [x] Keep `get_files_with_incomplete_tags(self, expected_heads, namespace_prefix, library_id) -> list[dict]` but update its AQL to reference `file_states/tagged` instead of `file_states/ml_tagged`
    **executor:** AQL string literal updated from "file_states/ml_tagged" to "file_states/tagged". Same signature.
- [x] Keep `clear_ml_tagged_batch(self, file_ids: list[str]) -> int` but rename to `clear_tagged_batch` and update AQL to reference `STATE_TAGGED`
    **executor:** Renamed to clear_tagged_batch. AQL bind var uses STATE_TAGGED instead of _STATE_ML_TAGGED.
- [x] Update module docstring to describe the new pure-boolean axis model
    **executor:** Module docstring replaced with pure-boolean axis model description. Removed logging, now_ms imports and logger. Kept cast, Any, TYPE_CHECKING, DatabaseLike, Cursor.

### Phase 6: Update bootstrap to seed all 16 vertices
- [x] Rewrite `_seed_file_states()` in `arango_bootstrap_comp.py` to seed all 16 state vertices (8 positive + 8 negative) by importing `ALL_STATE_VERTICES` from `file_states_aql`
    **executor:** Rewrote _seed_file_states to import ALL_STATE_VERTICES and seed all 16 vertices. Fixed RUF002 ambiguous unicode char in docstring. Zero lint errors in bootstrap file.
  **Notes:** Import `ALL_STATE_VERTICES` from `nomarr.persistence.database.file_states_aql`. Loop over the tuple and insert each as `{"_key": key}` with `contextlib.suppress(DocumentInsertError)`. The key is the part after `file_states/` — extract via `vertex.split("/")[1]`.
- [x] Verify `_seed_file_states` is called from `ensure_schema` (existing call — no change needed, just verify)
    **executor:** Verified: ensure_schema calls _create_collections which calls _seed_file_states(db) at line 144. Call chain intact, no changes needed.

### Phase 7: Validation
- [x] Run `lint_project_backend` on `nomarr/persistence/database/file_states_aql.py` and `nomarr/components/platform/arango_bootstrap_comp.py` — fix any type errors or import issues
    **executor:** Lint clean on both target files. All 18 errors are in caller files (library_files_aql submodules) referencing removed methods — expected, deferred to Plan C/D.
  **Warning:** Lint will report errors in callers of removed methods (Part C/D scope). Only fix errors IN the two files touched by this plan. Caller breakage is expected and resolved by later plans.
- [x] Verify the plan file parses correctly with `plan_read`
    **executor:** Plan parses correctly. All 24 steps across 7 phases verified complete.

## Completion Criteria
- `file_states_aql.py` exports 16 `STATE_*` constants and `ALL_STATE_VERTICES` tuple
- `FileStatesOperations` has `_transition_state` private method using REMOVE + INSERT
- All 16 axis setters exist (8 positive, 8 negative) with pure boolean signatures
- `bulk_set_not_calibrated()` and `bulk_set_tags_stale(library_id)` exist
- `initialize_file_states()` and `initialize_file_states_batch()` create all-negative edges
- Discovery methods use INBOUND traversal on negative vertices
- `discover_next_untagged_file` excludes `too_short` files via set difference
- `get_uncalibrated_tagged_file_ids(library_id)` provides tagged-AND-uncalibrated intersection
- `get_calibration_status_by_library()` has no `calibration_hash` parameter
- Old payload-bearing methods are removed (not wrapped)
- `_seed_file_states()` seeds all 16 vertices
- Both files pass `lint_project_backend` individually

## References
- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md`
- Parts breakdown: `artifacts/designs/parts/file-state-graph/README.md`
- Contracts ledger: `artifacts/designs/parts/file-state-graph/CONTRACTS.md`
