# Design: File State Graph Completion

## Overview

Complete the `file_has_state` graph model so that state edges are pure boolean (no domain payload), and **negative states** (`not_tagged`, `not_too_short`, `tags_not_written`, …) enable O(1) inbound-traversal discovery instead of expensive full-scan subqueries.

**Scope boundary:** This design covers state edges and passthrough cleanup only. Domain-relationship edges (`file_tagged_by`, `file_calibrated_by`, model versioning, calibration snapshots) are **out of scope** — handled by separate work on calibration and model versioning.

## Requirements

1. **State edges become boolean** — no `version`, `hash`, `mode`, or timestamps on `file_has_state` edges.
2. **Negative state vertices** — every state axis has positive/negative vertices. A file always has exactly one edge per axis.
3. **`too_short` is a proper state axis** — a too-short file was never tagged; it shouldn't have a `tagged` state it doesn't actually have.
4. **"Reconciled" is replaced by two axes** — `tags_written`/`tags_not_written` (have tags been physically written to disk?) and `tags_current`/`tags_stale` (do DB tags still match what's on disk?). "Reconciled" conflated two distinct questions.
5. **File properties stay on the file document** — `write_mode` (last tag-write mode used) is an attribute of `library_files`.
6. **Passthrough mixins are eliminated** — callers access `db.file_states.*` directly or logic moves to components.
7. **Direct AQL bypasses are funneled through `FileStatesOperations`** — `validate_scan_state_comp`, `worker_claims_aql`, `queries.py` inline AQL is consolidated.
8. **Bootstrap seeds all state vertices** — including new negative states.
9. **Forward-only migration** strips edge payloads, seeds negative states, renames vertices.
10. **Domain relationship edges are deferred** — `version`, `tagged_at`, `hash`, `calibrated_at` data on edges will be dropped (not migrated to new collections). Model/calibration linkage is separate work.

## Architecture

### State Axes

Each state axis is a pair of mutually exclusive singleton vertices. A file has **exactly one** `file_has_state` edge per axis at all times.

 | Axis | Positive Vertex | Negative Vertex | Semantics |
 | ------ | ---------------- | ---------------- | ----------- |
 | tagging | `file_states/tagged` | `file_states/not_tagged` | File has ML predictions in DB |
 | too_short | `file_states/too_short` | `file_states/not_too_short` | File is below minimum duration for ML processing |
 | calibration | `file_states/calibrated` | `file_states/not_calibrated` | File's mood tags match current calibration |
 | tag write | `file_states/tags_written` | `file_states/tags_not_written` | Tags have been physically written to disk |
 | tag freshness | `file_states/tags_current` | `file_states/tags_stale` | Disk tags match DB state (becomes stale on recalibration, bulk retag, manual curation) |
 | scan | `file_states/scanned` | `file_states/not_scanned` | File has been processed by scanner |
 | vectors | `file_states/vectors_extracted` | `file_states/not_vectors_extracted` | File has embedding vectors |
 | error | `file_states/errored` | `file_states/not_errored` | File encountered processing error |

**Vertex rename:** `file_states/ml_tagged` → `file_states/tagged` (migration creates new vertex, repoints edges).

**`too_short` semantics:** A file that is `too_short` is NOT `tagged` — it's a separate axis. A file can be `not_tagged` + `too_short` (short file, never processed) or `tagged` + `not_too_short` (normal file, processed). The combination `tagged` + `too_short` is invalid — the state initialization and transition logic must prevent it.

**Tag write vs. tag freshness:**

- `tags_written` / `tags_not_written` answers: "have we ever written tags to this file's audio metadata?"
- `tags_current` / `tags_stale` answers: "if we wrote tags, are they still correct?" Triggers for `tags_stale`:
  - Recalibration changes mood scores
  - Bulk retag operation changes tag values
  - Manual curation edits tags
  - Target write mode changes
- A file that is `tags_not_written` is implicitly also `tags_stale` (nothing written = nothing current). But we track both axes independently for clarity.

**Transition pattern:** ArangoDB does not permit updating `_to` on existing edges. State transitions REMOVE the old edge and INSERT the new one:

```aql
LET old = FIRST(
    FOR e IN file_has_state
        FILTER e._from == @file_id
            AND (e._to == @positive OR e._to == @negative)
        RETURN e
)
LET _ = old != null ? (REMOVE old._key IN file_has_state) : null
INSERT { _from: @file_id, _to: @new_state } INTO file_has_state
```

This is wrapped in `FileStatesOperations._transition_state()` — a single private method all state setters call.

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `file_states_aql.py` | Persistence | State CRUD, transitions, traversal queries |
 | `library_files_aql/calibration.py` | Persistence | **DELETE** — passthroughs absorbed into `file_states_aql` |
 | `library_files_aql/status.py` | Persistence | **DELETE** — passthroughs absorbed into `file_states_aql` |
 | `library_files_aql/reconciliation.py` | Persistence | Keep claim logic; state delegation updated to new axes |
 | `library_files_aql/queries.py` | Persistence | Remove inline `file_has_state` joins; use state traversals |
 | `worker_claims_aql.py` | Persistence | Replace inline edge checks with state vertex references |
 | `validate_scan_state_comp.py` | Component | Replace direct AQL with `db.file_states.*` calls |
 | `arango_bootstrap_comp.py` | Component | Seed all vertices including negatives |
 | `V022_file_state_graph_completion.py` | Migration | Strip payloads, seed negatives, rename vertices |

### Data Model

#### New State Vertices (seeded by migration + bootstrap)

Negative vertices:

```
file_states/not_tagged
file_states/not_too_short
file_states/not_calibrated
file_states/tags_not_written
file_states/tags_stale
file_states/not_scanned
file_states/not_vectors_extracted
file_states/not_errored
```

Positive vertices (new or renamed):

```
file_states/tagged          (renamed from ml_tagged)
file_states/tags_written    (replaces reconciled — write axis)
file_states/tags_current    (replaces reconciled — freshness axis)
```

Existing vertices retained as-is:

```
file_states/too_short
file_states/calibrated
file_states/scanned
file_states/vectors_extracted
file_states/errored
```

Retired vertices (no edges post-migration, kept for backward compat):

```
file_states/ml_tagged       (replaced by tagged)
file_states/reconciled      (replaced by tags_written + tags_current)
```

#### File Document Changes

**No changes to `library_files` documents.**

- `write_mode` (`mode` on old reconciled edge) is **not migrated** — it's redundant. The library's `file_write_mode` is the source of truth (already on `libraries` document). When write mode changes, `bulk_set_tags_stale()` marks all files stale. No per-file mode tracking needed.
- `has_nomarr_namespace` (`has_namespace` on old reconciled edge) is **dropped entirely** — write-only data, nothing ever reads it back. If reconciliation needs it, it checks the actual audio file at write time.

### Discovery Patterns (Before → After)

 | Query | Before (O(n) scan) | After (O(1) traversal) |
 | ------- | ------- | ------- |
 | Find untagged file | `FOR file IN library_files ... subquery edge absence` | `FOR file IN INBOUND 'file_states/not_tagged' file_has_state LIMIT 1` |
 | Count untagged | Same scan + COUNT | `RETURN LENGTH(FOR f IN INBOUND 'file_states/not_tagged' file_has_state RETURN 1)` |
 | Find uncalibrated | Scan + subquery | `FOR file IN INBOUND 'file_states/not_calibrated' file_has_state` |
 | Find files needing write | Scan with double subquery | `FOR file IN INBOUND 'file_states/tags_not_written' file_has_state` |
 | Find stale files | N/A (was mode/hash mismatch check) | `FOR file IN INBOUND 'file_states/tags_stale' file_has_state` |
 | Find too-short files | Scan for `too_short` edge | `FOR file IN INBOUND 'file_states/too_short' file_has_state` |

**Library-scoped queries use set intersection** (chosen over filtered traversal):

```aql
LET untagged_ids = (
    FOR f IN INBOUND 'file_states/not_tagged' file_has_state RETURN f._id
)
FOR file IN OUTBOUND @library_id library_contains_file
    FILTER file._id IN untagged_ids
    LIMIT @limit
    RETURN file
```

### Tag Write / Freshness Logic (replaces "Reconciliation")

Old reconciliation checked 3 conditions on edges:

1. Has `ml_tagged` edge (file has ML tags)
2. Missing `reconciled` edge, or `mode` mismatch, or `calibration_hash` mismatch

New model with two axes:

**`tags_written` / `tags_not_written` — write tracking:**

- Set to `tags_written` when tags are physically written to disk
- Set to `tags_not_written` on file creation (initial state)
- Claim management stays in `reconciliation.py` mixin (real logic, not passthrough)

**`tags_current` / `tags_stale` — freshness tracking:**

- Set to `tags_current` after successful tag write
- Set to `tags_stale` when:
  - Calibration changes (bulk transition: all `tags_current` → `tags_stale`)
  - Manual tag curation edits DB tags
  - Bulk retag operation changes tag values
  - Library `file_write_mode` changes → `bulk_set_tags_stale(library_id)` for all files in that library
- Discovery: "what needs rewriting?" = `INBOUND 'file_states/tags_stale' file_has_state`

**Transition side effects:**

- When `tagged` is set → also set `tags_stale` (new tags exist, not yet written)
- When tags are written → set `tags_written` + `tags_current`
- When calibration changes → bulk `tags_current` → `tags_stale`

### API Surface Changes

#### `FileStatesOperations` — New/Changed Methods

```python
# New: generic state transition (private)
def _transition_state(self, file_id: str, axis: str, to_positive: bool) -> None

# Tagging axis (renamed from set_ml_tagged, no payload)
def set_tagged(self, file_id: str) -> None
def set_not_tagged(self, file_id: str) -> None

# Too-short axis (proper axis, not annotation)
def set_too_short(self, file_id: str) -> None
def set_not_too_short(self, file_id: str) -> None

# Calibration axis (no payload — hash/timestamp deferred to separate work)
def set_calibrated(self, file_id: str) -> None
def set_not_calibrated(self, file_id: str) -> None

# Tag write axis (replaces reconciled)
def set_tags_written(self, file_id: str) -> None
def set_tags_not_written(self, file_id: str) -> None

# Tag freshness axis (new)
def set_tags_current(self, file_id: str) -> None
def set_tags_stale(self, file_id: str) -> None

# Bulk transitions
def bulk_set_not_calibrated(self) -> int
def bulk_set_tags_stale(self, library_id: str | None = None) -> int

# Fast discovery (replaces scan-based methods)
def discover_next_untagged_file(self, ...) -> dict[str, Any] | None  # INBOUND traversal
def get_untagged_file_ids(self, ...) -> list[str]
def count_untagged_files(self, ...) -> int
def count_uncalibrated_files(self) -> int
def get_stale_file_ids(self, library_id: str | None = None) -> list[str]  # New

# Initialize state for new file (all negative)
def initialize_file_states(self, file_id: str) -> None
def initialize_file_states_batch(self, file_ids: list[str]) -> None
```

#### `LibraryFilesOperations` Changes

- `upsert_library_file()` calls `db.file_states.initialize_file_states()` for new files
- `upsert_batch()` calls `db.file_states.initialize_file_states_batch()` for new files
- Remove `calibration.py` mixin, `status.py` mixin
- Slim down `reconciliation.py` mixin to claim logic only (using new `tags_written`/`tags_stale` axes)

#### Callers Update Map

 | Caller | Current Call | New Call |
 | -------- | ------------- | ---------- |
 | `tagging_svc.py` | `db.library_files.mark_file_tagged(id, ver)` | `db.file_states.set_tagged(id)` |
 | `ml_calibration_state_comp.py` | `db.library_files.update_calibration_hash(id, hash)` | `db.file_states.set_calibrated(id)` |
 | `ml_calibration_state_comp.py` | `db.library_files.update_calibration_hashes_batch(items)` | `db.file_states.set_calibrated(id)` per item (or batch method) |
 | `ml_calibration_state_comp.py` | `db.library_files.clear_all_calibration_hashes()` | `db.file_states.bulk_set_not_calibrated()` |
 | `ml_calibration_state_comp.py` | `db.library_files.get_calibration_status_by_library(hash)` | `db.file_states.get_calibration_status_by_library(hash)` (move method) |
 | `tagging_svc.py` | `db.library_files.get_calibration_status_by_library(hash)` | Same — direct to `db.file_states` |
 | `validate_library_tags_wf.py` | Direct file_states call | Same (already correct layer) |
 | `validate_scan_state_comp.py` | Direct AQL INSERT | `db.file_states.set_too_short(id)` or `db.file_states.set_tagged(id)` |
 | `worker_claims_aql.py` | Inline `file_has_state` check | Update vertex name to `file_states/tagged` |
 | `queries.py` | Inline edge join for `tagged_at` | **Drop `tagged_at` from queries** (deferred to model versioning work) |
 | `queries.py` | Edge existence check | `INBOUND 'file_states/tagged'` traversal |
 | `reconciliation.py` | `get_files_needing_reconciliation` | `INBOUND 'file_states/tags_stale'` + library intersection |
 | `reconciliation.py` | `set_file_written` → `set_reconciled` | `set_tags_written` + `set_tags_current` |
 | `library_if.py` | `update_write_mode` → updates library doc only | Also call `db.file_states.bulk_set_tags_stale(library_id)` after mode change |
 | `library_files_aql/stats.py` | `count_untagged_files` via file_states | Same — already correct layer |
 | `library_files_aql/stats.py` | `count_recently_tagged` via file_states | **Drop or defer** (needs `tagged_at` which is being removed) |

### Indexes

```python
# file_has_state: ensure _to persistent index exists (critical for INBOUND traversal)
# V001 baseline may not have created explicit persistent indexes
# Edge collections auto-create _from/_to indexes but verify persistent index on _to
_ensure_index(db, "file_has_state", "persistent", ["_to"])
_ensure_index(db, "file_has_state", "persistent", ["_from", "_to"], unique=True)
```

No new edge collections in this work — domain relationship edges are deferred.

### Graph Definition Updates

No changes to `file_graph` edge definitions in this work. The `file_has_state` edge collection already exists in the graph. New `_to` vertices in `file_states` are automatically valid targets.

## Migration: V022_file_state_graph_completion.py

### Phase 1: DDL + Vertex Seeding

1. Seed new state vertices:
   - `tagged` (rename target for `ml_tagged`)
   - `not_tagged`, `not_too_short`, `not_calibrated`
   - `tags_written`, `tags_not_written`, `tags_current`, `tags_stale`
   - `not_scanned`, `not_vectors_extracted`, `not_errored`
2. Ensure persistent index on `file_has_state._to` (for INBOUND traversal)
3. Ensure persistent index on `file_has_state._from,_to` unique (for transition upserts)

### Phase 2: Data Migration

1. **Repoint `ml_tagged` → `tagged`:**

   ```aql
   FOR edge IN file_has_state
       FILTER edge._to == "file_states/ml_tagged"
       REMOVE edge IN file_has_state
       INSERT { _from: edge._from, _to: "file_states/tagged" }
       INTO file_has_state OPTIONS { ignoreErrors: true }
   ```

2. **Convert `reconciled` edges → `tags_written` + `tags_current` edges (drop `mode` — library owns it):**

   ```aql
   FOR edge IN file_has_state
       FILTER edge._to == "file_states/reconciled"

       -- Remove old reconciled edge
       REMOVE edge IN file_has_state

       -- Create tags_written edge
       INSERT { _from: edge._from, _to: "file_states/tags_written" }
       INTO file_has_state OPTIONS { ignoreErrors: true }

       -- Create tags_current edge
       INSERT { _from: edge._from, _to: "file_states/tags_current" }
       INTO file_has_state OPTIONS { ignoreErrors: true }
   ```

3. **Strip payload attributes from all remaining state edges:**

   ```aql
   FOR edge IN file_has_state
       FILTER edge.version != null OR edge.hash != null OR edge.mode != null
           OR edge.tagged_at != null OR edge.calibrated_at != null
           OR edge.calibration_hash != null OR edge.written_at != null
           OR edge.has_namespace != null
       UPDATE edge WITH {
           version: null, tagged_at: null,
           hash: null, calibrated_at: null,
           mode: null, calibration_hash: null,
           written_at: null, has_namespace: null
       } IN file_has_state OPTIONS { keepNull: false }
   ```

4. **Seed negative states for files missing edges on each axis:**

   For each axis (tagged/not_tagged, too_short/not_too_short, calibrated/not_calibrated, tags_written/tags_not_written, tags_current/tags_stale, scanned/not_scanned, vectors_extracted/not_vectors_extracted, errored/not_errored):

   ```aql
   FOR file IN library_files
       LET has_axis = LENGTH(
           FOR e IN file_has_state
               FILTER e._from == file._id
                   AND (e._to == @positive OR e._to == @negative)
               LIMIT 1 RETURN 1
       )
       FILTER has_axis == 0
       INSERT { _from: file._id, _to: @negative }
       INTO file_has_state OPTIONS { ignoreErrors: true }
   ```

   Special case: files with existing `too_short` edge already have the positive state — they get `not_too_short` skipped.

### Phase 3: Cleanup

1. Payload attributes stripped in Phase 2 step 3
2. Old vertices (`ml_tagged`, `reconciled`) remain — harmless, no edges point to them post-migration

## Constraints

- **Forward-only** — no rollback function in migration
- **Idempotent** — all steps use `ignoreErrors: true` or conditional guards
- **Self-repairing** — bootstrap seeds all vertices; `initialize_file_states()` on file creation ensures new files start with negative states
- **No breaking callers** — all ~24 `FileStatesOperations` methods get updated, callers migrate
- **ArangoDB edge immutability** — `_from` and `_to` cannot be updated on existing edges; transitions must REMOVE + INSERT
- **Domain edges deferred** — `file_tagged_by`, `file_calibrated_by`, `calibration_snapshots` are out of scope for this work. Dropping `version`/`hash`/`tagged_at`/`calibrated_at` data from state edges means that data is *lost* until domain edge work is done. Acceptable for alpha.

## Decisions Log

 | # | Decision | Rationale |
 | --- | ---------- | ----------- |
 | 1 | `too_short` is a proper boolean axis with `not_too_short` inverse | A too-short file was never tagged — shouldn't have a state it doesn't have |
 | 2 | "Reconciled" split into `tags_written`/`tags_not_written` + `tags_current`/`tags_stale` | Old name conflated "have we written?" and "is what we wrote still correct?" — needs separation for bulk retag and manual curation features |
 | 3 | Domain relationship edges (`file_tagged_by`, `file_calibrated_by`) deferred | Model versioning and calibration linkage are active separate work; don't touch here |
 | 4 | `calibration_snapshots` collection deferred | Part of calibration domain work |
 | 5 | Library-scoped queries use set intersection | Filtered traversal is O(untagged × subquery), blows up on cold start. Intersection is bounded and predictable |
 | 6 | Payload data (`version`, `tagged_at`, `hash`, `calibrated_at`) is dropped, not migrated | Alpha policy — domain edges will restore this linkage when model/calibration work lands |
 | 7 | `has_nomarr_namespace` / `has_namespace` dropped entirely — not stored, not a state axis | YAGNI — write-only data, nothing ever reads it back. If reconciliation needs it, it checks the actual file at write time |
 | 8 | `mode` on reconciled edge dropped — not migrated to file doc | `file_write_mode` already lives on the `libraries` document (source of truth). Per-file mode was redundant staleness detection; replaced by `bulk_set_tags_stale(library_id)` on mode change |

## Appendix: Research Findings

### ArangoDB Edge Mutability

`_from` and `_to` are **immutable** on existing edge documents in ArangoDB. You cannot `UPDATE edge WITH { _to: newTarget }`. State transitions must REMOVE the old edge and INSERT a new one. The `_transition_state` helper encapsulates this as an atomic AQL statement.

### Existing Indexes on `file_has_state`

The V001 baseline creates `file_has_state` as an edge collection and adds:

- `_from,_to` composite persistent index (unique)
- `_to` persistent index

Edge collections also auto-create system indexes on `_from` and `_to`. The migration should verify the `_to` persistent index exists — it's critical for INBOUND traversal performance.

### Bootstrap vs. Migration Responsibility

`_seed_file_states()` in bootstrap only seeds 3 original vertices (`ml_tagged`, `calibrated`, `reconciled`). V021 seeds 5 more. After this work:

- Bootstrap seeds **all** vertices (positive + negative, all axes) — authoritative list
- Migration V022 also seeds them (for existing installs that run migration before next bootstrap)

### Direct AQL Bypass in `validate_scan_state_comp.py`

`_heal_short_files()` writes `file_has_state` edges directly with `INSERT ... INTO file_has_state`. Bypasses `FileStatesOperations`. Must be refactored to call `db.file_states.set_too_short(id)`.

### Worker Claims Inline AQL

`cleanup_completed_file_claims()` has inline `FOR edge IN file_has_state FILTER edge._to == "file_states/ml_tagged"`. After refactor, update vertex name to `file_states/tagged`.

### `count_recently_tagged` Impact

This method queries `tagged_at` on the `ml_tagged` edge. Since we're dropping edge payloads and deferring domain edges, this method loses its data source. Options:

- Drop the method (if unused or low-value)
- Track `tagged_at` on the file document temporarily
- Defer to model versioning work

Decision needed during implementation.
