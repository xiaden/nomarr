# Discovery Worker ERR 1579 Fix — Two-Phase AQL Separation — Design Document

**Status:** Completed  
**Author:** rnd-dd-author  
**Created:** 2026-04-06  

**Related Documents:**

- [](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) —
- [](artifacts/decisions/ADR-008-deferred-write-pattern-for-discovery-worker.md) —
- [](artifacts/designs/completed/DD-file-state-graph-completion.md) —

---

## Scope

nomarr/persistence/database/file_states_aql.py, nomarr/persistence/database/navidrome_playcounts_aql.py, nomarr/persistence/database/vram_promises_aql.py, tests/

---

## Problem Statement

The discovery worker intermittently fails with ArangoDB **ERR 1579** (`access after data-modification by collection 'file_has_state'`). This is the **fourth occurrence** of this error class in the project.

### Root Cause

`_transition_state()` (file_states_aql.py:94-126) executes a single AQL query that **reads AND writes** `file_has_state` in the same statement:

```aql
LET old = FIRST(
    FOR e IN file_has_state          -- READ
        FILTER e._from == @file_id
            AND (e._to == @positive OR e._to == @negative)
        RETURN e
)
LET removed = (
    FOR o IN (old != null ? [old] : [])
        REMOVE o IN file_has_state   -- WRITE (remove)
        RETURN null
)
INSERT { _from: @file_id, _to: @new_state } INTO file_has_state  -- WRITE (insert)
```

This violates the project's documented rule: **"Never read and write the same collection in a single AQL statement."**

The error is intermittent because it depends on ArangoDB query optimizer plan selection and collection state at execution time. Empty or freshly-created collections often don't trigger it.

### Impact

All 16 `set_*`/`set_not_*` single-file methods route through `_transition_state`. The discovery worker hits this on `set_tagged()`, `set_vectors_extracted()`, and `set_errored()` inside `_execute_deferred_writes`. Additionally, **7 bulk methods** share the same anti-pattern with inline `FOR ... REMOVE ... INSERT` on `file_has_state`.

Two additional files outside `file_states_aql.py` share the same read+write-same-collection anti-pattern on different collections (see hazard map entries 11–12).

### Complete ERR 1579 Hazard Map

 | # | Method | Lines | Hazard | Pattern |
 | --- | -------- | ------- | -------- | --------- |
 | 1 | `_transition_state` | 94-126 | **CONFIRMED** | LET-read → REMOVE → INSERT |
 | 2 | `bulk_set_not_calibrated` | 188-209 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 3 | `bulk_set_tags_stale` (lib_id) | 211-245 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 4 | `bulk_set_tags_stale` (global) | 211-245 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 5 | `bulk_set_scanned` | 247-269 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 6 | `bulk_set_not_vectors_extracted` | 271-292 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 7 | `bulk_set_not_errored` | 294-316 | HIGH | FOR-read → REMOVE → INSERT in same loop |
 | 8 | `clear_tagged_batch` | 793-832 | HIGH | Separate FOR blocks but both touch @@coll |
 | 9 | `clear_all_states` | 838-863 | SAFE | Remove-only (no insert), write-only pattern |
 | 10 | `clear_all_states_batch` | 865-894 | SAFE | Remove-only (no insert), write-only pattern |
 | 11 | `NavidromePlaycountsOperations.increment_play` | navidrome_playcounts_aql.py:105-167 | HIGH | LET-read `@@has_plays` → REMOVE → INSERT in same statement; also UPSERT on `@@playcounts` |
 | 12 | `VramPromisesOperations.try_register` | vram_promises_aql.py:80-151 | HIGH | LET-read `vram_promises` (SUM aggregate) → INSERT into `vram_promises` in same statement |

---

## Architecture

## Fix Strategy: Two-Phase AQL Separation

All hazardous methods will be rewritten to use **separate Python-level `aql.execute()` calls** for read and write phases. This is the proven safe pattern already used in migration V021.

### 1. `_transition_state` — Two-Phase Replacement

The core fix that resolves all 16 `set_*`/`set_not_*` methods:

```python
def _transition_state(self, file_id: str, axis: str, to_positive: bool) -> None:
    positive, negative = AXIS_PAIRS[axis]
    new_state = positive if to_positive else negative

    # Phase 1: READ — find existing edge key (if any)
    cursor = self.db.aql.execute(
        """
        FOR e IN file_has_state
            FILTER e._from == @file_id
                AND (e._to == @positive OR e._to == @negative)
            RETURN e._key
        """,
        bind_vars={
            "file_id": file_id,
            "positive": positive,
            "negative": negative,
        },
    )
    old_key: str | None = next(cursor, None)

    # Phase 2: WRITE — remove old + insert new (both writes, no reads)
    if old_key is not None:
        self.db.aql.execute(
            """
            REMOVE @old_key IN file_has_state
            """,
            bind_vars={"old_key": old_key},
        )

    self.db.aql.execute(
        """
        INSERT { _from: @file_id, _to: @new_state } INTO file_has_state
        """,
        bind_vars={
            "file_id": file_id,
            "new_state": new_state,
        },
    )
```

**Design decisions:**

- **Three separate calls** (read, remove, insert) rather than combining REMOVE+INSERT. The combined write-only statement is also safe per AQL rules (both are writes, no read), but three calls are maximally defensive and trivially correct.
- **First-time state setting**: When `old_key is None`, no edge exists yet for this axis. We skip the REMOVE and go straight to INSERT. This handles initial state assignment after file discovery.
- **Race conditions**: Concurrent workers could read the same edge key. The REMOVE-by-key is idempotent — if another worker already removed it, the REMOVE is a no-op (ArangoDB ignores missing keys with default options). The INSERT may create a duplicate edge in a narrow window, but `_transition_state` is called per-file-per-worker with claim-based exclusion, so this race is prevented at the orchestration layer. If additional safety is needed, an `OPTIONS { ignoreErrors: true }` can be added.

### 2. Bulk Method Fixes — Read-then-Write Pattern

All 6 hazardous bulk methods (`bulk_set_not_calibrated`, `bulk_set_tags_stale`, `bulk_set_scanned`, `bulk_set_not_vectors_extracted`, `bulk_set_not_errored`) share the same anti-pattern:

```aql
FOR e IN file_has_state
    FILTER e._to == @old_state
    LET r = (REMOVE e._key IN file_has_state RETURN 1)
    INSERT { _from: e._from, _to: @new_state } INTO file_has_state
    RETURN 1
```

**Replacement pattern** (same for all):

```python
def bulk_set_not_calibrated(self) -> int:
    # Phase 1: READ — collect edge keys and source file IDs
    cursor = self.db.aql.execute(
        """
        FOR e IN file_has_state
            FILTER e._to == @calibrated
            RETURN { key: e._key, from_id: e._from }
        """,
        bind_vars={"calibrated": STATE_CALIBRATED},
    )
    edges = list(cursor)
    if not edges:
        return 0

    keys = [e["key"] for e in edges]
    from_ids = [e["from_id"] for e in edges]

    # Phase 2: REMOVE old edges
    self.db.aql.execute(
        """
        FOR k IN @keys
            REMOVE k IN file_has_state
        """,
        bind_vars={"keys": keys},
    )

    # Phase 3: INSERT new edges
    self.db.aql.execute(
        """
        FOR fid IN @from_ids
            INSERT { _from: fid, _to: @not_calibrated } INTO file_has_state
        """,
        bind_vars={"from_ids": from_ids, "not_calibrated": STATE_NOT_CALIBRATED},
    )
    return len(edges)
```

The `bulk_set_tags_stale` library-scoped variant adds a LET subquery for `OUTBOUND @library_id library_contains_file` — this stays in the Phase 1 read query since `library_contains_file` is a different collection and is read-only.

### 3. `clear_tagged_batch` Fix

Current code has two sequential FOR blocks in one statement — one REMOVEs, one INSERTs:

```aql
FOR edge IN @@coll
    FILTER edge._from IN @file_ids AND edge._to == @tagged
    REMOVE edge IN @@coll

FOR fid IN @file_ids
    INSERT { _from: fid, _to: @not_tagged } INTO @@coll
```

The second FOR block is a write into a collection that the first block also wrote to. While there's no read-after-write in the second block, the entire statement shares an execution context. Split into two calls:

```python
# Phase 1: REMOVE tagged edges
self.db.aql.execute(
    "FOR edge IN @@coll FILTER edge._from IN @file_ids AND edge._to == @tagged REMOVE edge IN @@coll",
    bind_vars={"file_ids": file_ids, "tagged": STATE_TAGGED, "@coll": _EDGE_COLLECTION},
)
# Phase 2: INSERT not_tagged edges
self.db.aql.execute(
    """
    FOR fid IN @file_ids
        INSERT { _from: fid, _to: @not_tagged } INTO @@coll
        OPTIONS { ignoreErrors: true }
    """,
    bind_vars={"file_ids": file_ids, "not_tagged": STATE_NOT_TAGGED, "@coll": _EDGE_COLLECTION},
)
```

### 4. AST-Based Safety Test

A pytest test that statically scans all Python source for AQL queries that read and write the same collection in one statement. This prevents regression.

**Approach:**

1. **Find AQL strings**: Use Python `ast` module to walk all `.py` files under `nomarr/` (and optionally `scripts/` — see scan scope note below). Find calls to `aql.execute(...)` and extract the first positional string argument (handles plain strings and joined strings, skips f-strings with dynamic collection names).

2. **Detect UNSAFE read/write conflicts**: The detection must distinguish safe single-pass modification from hazardous cross-operation read+write patterns:

   **SAFE — single-pass modification (whitelist, do NOT flag):**

   ```aql
   FOR doc IN collection FILTER ... UPDATE doc WITH { ... } IN collection
   FOR doc IN collection FILTER ... REMOVE doc IN collection
   ```

   These modify the document being iterated — standard ArangoDB pattern with no cross-operation hazard.

   **UNSAFE — cross-operation read then write (flag as violations):**
   - **Pattern A — LET-read before separate write:** `LET var = FIRST(FOR ... IN {coll} ...)` followed by `INSERT ... INTO {coll}` or `REMOVE ... IN {coll}` as a separate operation. The read and write are different AQL operations on the same collection.
   - **Pattern B — Loop body with REMOVE + INSERT:** `FOR ... IN {coll}` whose body contains BOTH `REMOVE ... IN {coll}` AND `INSERT ... INTO {coll}`. This is the bulk method anti-pattern where the loop reads a document, removes it, and inserts a replacement — the INSERT is a separate write, not a modification of the iterated document.

   **Key distinguishing factor:** Unsafe patterns have a separate INSERT or write operation that isn't the direct modification of the iterated document. `FOR x IN coll UPDATE x IN coll` modifies the iterated document (safe). `FOR x IN coll REMOVE x IN coll INSERT new INTO coll` does a separate INSERT that creates a different document (unsafe).

3. **Detection regexes** (refined to avoid false positives):

   ```python
   # Pattern A: LET-read followed by separate write on same collection
   # Detects: LET ... FIRST(FOR ... IN {coll}) ... INSERT/REMOVE ... IN {coll}
   _RE_LET_READ = re.compile(
       r"LET\s+\w+.*?FOR\s+\w+\s+IN\s+(@@?\w+|\w+)",
       re.IGNORECASE | re.DOTALL,
   )
   _RE_SEPARATE_WRITE = re.compile(
       r"(?:INSERT|UPSERT)\s+.*?\bIN(?:TO)?\s+(@@?\w+|\w+)",
       re.IGNORECASE | re.DOTALL,
   )

   # Pattern B: FOR-loop with both REMOVE and INSERT on same collection
   _RE_FOR_IN = re.compile(
       r"FOR\s+\w+\s+IN\s+(?!OUTBOUND|INBOUND|ANY|@\w)\s*(@@?\w+|\w+)",
       re.IGNORECASE | re.DOTALL,
   )
   _RE_REMOVE_IN = re.compile(
       r"REMOVE\s+.*?\bIN\s+(@@?\w+|\w+)",
       re.IGNORECASE | re.DOTALL,
   )
   _RE_INSERT_IN = re.compile(
       r"INSERT\s+.*?\bIN(?:TO)?\s+(@@?\w+|\w+)",
       re.IGNORECASE | re.DOTALL,
   )
   ```

   The conflict detection function:

   ```python
   def _find_read_write_conflicts(aql: str) -> set[str]:
       """Return collection names involved in unsafe read+write patterns."""
       conflicts: set[str] = set()

       # Pattern A: LET-read + separate write on same collection
       let_read_colls = {m.group(1).lower() for m in _RE_LET_READ.finditer(aql)}
       separate_write_colls = {m.group(1).lower() for m in _RE_SEPARATE_WRITE.finditer(aql)}
       conflicts |= let_read_colls & separate_write_colls

       # Pattern B: FOR-loop iterating collection + body has REMOVE AND INSERT on it
       for_colls = {m.group(1).lower() for m in _RE_FOR_IN.finditer(aql)}
       remove_colls = {m.group(1).lower() for m in _RE_REMOVE_IN.finditer(aql)}
       insert_colls = {m.group(1).lower() for m in _RE_INSERT_IN.finditer(aql)}
       for coll in for_colls:
           if coll in remove_colls and coll in insert_colls:
               conflicts.add(coll)

       return conflicts
   ```

4. **Edge cases handled**:
   - Bind variables (`@@coll`): treated as a single token — if `@@coll` appears in both read and write positions, it's flagged
   - Multi-line strings: regex uses `re.DOTALL`
   - `OUTBOUND`/`INBOUND` graph traversals: excluded from `FOR ... IN` read detection (the identifier after `IN OUTBOUND` is a start vertex, not a collection)
   - Write-only patterns (e.g., `FOR k IN @keys REMOVE k IN coll`): `@keys` (single `@`) is a bind parameter array, NOT a collection — correctly excluded
   - **Single-pass modifications** (`FOR doc IN coll UPDATE doc IN coll`): Only REMOVE on `coll` is flagged when paired with INSERT on the same `coll` — a lone UPDATE or lone REMOVE without INSERT is safe

5. **Files that would be false-positived by a naive regex** (these are safe, and the refined detection correctly ignores them):
   - `health_aql.py`, `worker_restart_policy_aql.py`, `locks_aql.py`, `db.py` — single-pass `FOR doc IN coll UPDATE/REMOVE doc IN coll`
   - `library_files_aql/crud.py` — `FOR doc IN coll UPDATE doc IN coll` patterns
   - `ml_vector_maintenance_comp.py` — `FOR doc IN coll REMOVE doc IN coll`

6. **Scan scope**: Primary scan path is `Path("nomarr").rglob("*.py")` (including `nomarr/migrations/`). Four files in `scripts/` also contain `aql.execute` calls (`scripts/consolidate_migrations.py`, `scripts/consolidate_migrations/__main__.py`, `scripts/diagnostics/head_calibration_audit.py`, `scripts/tools/check_calibration_state.py`). These are dev/diagnostic tools, not production code. The scan should optionally include `scripts/` for completeness but the primary assertion covers `nomarr/` only. Consider a secondary soft check (warning, not failure) for `scripts/`.

7. **Test location**: `tests/unit/test_aql_safety.py`

### 5. Additional Hazardous Files (Outside file_states_aql.py)

Two files outside `file_states_aql.py` have the same read+write-same-collection anti-pattern on different collections. Fix with the same two-phase separation.

#### 5a. `NavidromePlaycountsOperations.increment_play` (navidrome_playcounts_aql.py:105-167)

**Current hazard:** Single AQL statement reads `@@has_plays` via `LET existing = FIRST(FOR e IN @@has_plays ...)`, then writes `@@has_plays` via `REMOVE { _key: existing.edge_key } IN @@has_plays` and `INSERT ... IN @@has_plays`. Also performs `UPSERT ... IN @@playcounts` (separate collection, safe by itself).

**Fix:** Split into three Python-level `aql.execute()` calls:

1. **READ** — Find the existing edge key and old playcount from `@@has_plays`
2. **WRITE (upsert bucket + remove old edge)** — UPSERT the new bucket vertex in `@@playcounts` and REMOVE old edge from `@@has_plays` (both are writes, safe to combine since they target different collections, or split further for maximum safety)
3. **WRITE (insert new edge)** — INSERT new edge into `@@has_plays`

Note: UPSERT on `@@playcounts` is a write-only operation (no prior read of that collection in the same statement), so it can remain combined or be separated as preferred.

#### 5b. `VramPromisesOperations.try_register` (vram_promises_aql.py:80-151)

**Current hazard:** Single AQL statement reads `vram_promises` via `LET sum_promised = FIRST(FOR p IN vram_promises COLLECT AGGREGATE ...)`, then writes `vram_promises` via `INSERT { ... } INTO vram_promises OPTIONS { overwriteMode: "replace" }`.

**Fix:** Split into two Python-level `aql.execute()` calls:

1. **READ** — Compute the aggregate sum of promised VRAM from `vram_promises`
2. **WRITE** — If headroom check passes (in Python), INSERT/REPLACE the promise document into `vram_promises`

**Race condition note:** The existing code's docstring acknowledges a theoretical TOCTOU race between read and write, mitigated by the 256 MB reserve buffer. The two-phase split does not worsen this — the single-statement version was never truly atomic for concurrent workers (ArangoDB doesn't lock the collection for the full statement). The reserve buffer remains the safety mechanism.

These fixes should be included in **Phase 2** alongside bulk method fixes, or as a separate **Phase 2b** if the team prefers to isolate non-file-state changes.

---

### 6. Caller Impact

Fixing `_transition_state` (Phase 1) automatically fixes ALL 16 single-file `set_*` methods and their ~20 production callers. Bulk method fixes (Phase 2) cover the remaining ~15 callers. No caller-side code changes are needed — the API contracts are unchanged.

 | Caller Group | Methods Called | Call Sites | Fixed By |
 | --- | --- | --- | --- |
 | **Discovery worker** | `set_tagged` ×2, `set_vectors_extracted`, `set_errored` ×2 | 5 | Phase 1 (`_transition_state`) |
 | **Tagging service** | `bulk_set_tags_stale`, `set_tags_not_written` ×3 | 4 | Phase 2 (bulk) + Phase 1 |
 | **Library service/files** | `bulk_set_not_errored`, `clear_tagged_batch` | 2 | Phase 2 (bulk) |
 | **Scan workflows** (full/quick) | `bulk_set_scanned` ×6, `bulk_set_not_errored` ×6 | 12 | Phase 2 (bulk) |
 | **Calibration state component** | `set_calibrated` ×2, `bulk_set_not_calibrated`, `bulk_set_not_vectors_extracted` | ~5 | Phase 1 + Phase 2 |
 | **Library components** | `set_too_short`, `set_tagged` ×2 | 3 | Phase 1 (`_transition_state`) |
 | **Validate library tags workflow** | `clear_tagged_batch` | 1 | Phase 2 (bulk) |
 | **Reconciliation persistence** | `set_tags_written`, `set_tags_current` | 2 | Phase 1 (`_transition_state`) |
 | **Library files CRUD** | `set_tagged` | 1 | Phase 1 (`_transition_state`) |
 | **Navidrome playcounts callers** | `increment_play` | TBD | Phase 2/2b |
 | **VRAM promise callers** | `try_register` | TBD | Phase 2/2b |

**Key insight:** Phase 1 alone fixes the immediate ERR 1579 crash in the discovery worker AND all ~20 callers that route through `_transition_state`. Phase 2 is preventive — those bulk methods haven't triggered ERR 1579 yet but are statically hazardous.

---

### 7. Methods NOT Requiring Changes

- `clear_all_states` / `clear_all_states_batch`: These iterate `file_has_state` and REMOVE from it — this is write-only (the `FOR` provides the iteration cursor, and `REMOVE` consumes it). No INSERT follows. This is a standard safe ArangoDB pattern. The `COLLECT WITH COUNT` aggregates the REMOVE results — it doesn't re-read the collection.
- All pure-read methods (`get_*`, `count_*`, `has_*`): No writes involved.

---

## Design Goals

1. **Eliminate ERR 1579** from all `file_has_state` operations by enforcing two-phase AQL separation
2. **Prevent regression** via an AST-based safety test that catches read-write-same-collection violations at CI time
3. **Preserve ADR-003 semantics**: singleton boolean edges, REMOVE+INSERT transitions, no payload changes
4. **Preserve ADR-008 patterns**: deferred writes remain the intentional architecture
5. **Minimal blast radius**: changes are confined to `file_states_aql.py` and a new test file

---

## Constraints

- **ADR-003**: File state modeled as singleton boolean edges in `file_has_state`; transitions use REMOVE + INSERT. This is preserved — only the AQL execution boundary changes.
- **ADR-008**: Deferred write patterns are intentional. The fix does not change when state transitions are called, only how the AQL is executed.
- **FileStatesOperations is the canonical owner** for all `file_has_state` transitions. No new inline AQL in workers/components.
- **Discovery worker runs as a subprocess** with its own DB connection. Claim-based exclusion prevents concurrent transitions of the same file.
- **Forward-only migrations if schema changes needed** — this fix does not change the schema.
- **Two-phase separation is the proven safe pattern** (V021 precedent).
- **Do NOT use streaming transactions** — would guarantee ERR 1579 within the transaction scope.
- **Do NOT attempt full AQL parsing** for the safety test — regex-based pattern detection per dead-end finding.

---

## Open Questions

1. **REMOVE-by-key error handling**: If a concurrent operation removes the edge between our read and write phases, should `_transition_state` silently ignore the missing key (current approach: yes, ArangoDB default) or raise? The claim system makes this unlikely but not impossible during admin operations.
2. **Bulk method atomicity**: The current single-AQL bulk methods are pseudo-atomic (succeed or fail as one query). The two-phase split means a crash between REMOVE and INSERT leaves files with a missing state edge. Is this acceptable given that the system already self-heals via negative-vertex discovery? (Likely yes — `ensure_file_states` can repair gaps.)
3. **Performance of three-call `_transition_state`**: Three round-trips vs one. The discovery worker processes files sequentially per worker, and network latency to local ArangoDB is negligible. No concern expected, but should be validated under load.
4. **Safety test scope**: Should the test also scan migration files under `nomarr/migrations/`? Migrations run once and are forward-only, so a read-write-same-collection pattern in a migration is a one-time risk, not a recurring one.

---
