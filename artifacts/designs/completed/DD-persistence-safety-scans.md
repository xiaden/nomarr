# Expanded AST Safety Scans and Shared Test Fixtures for the Persistence Layer — Design Document

**Status:** Completed  
**Author:** rnd-dd-author  
**Created:** 2026-04-06  

**Related Documents:**
- [ADR-003: Pure Boolean State Graph for File Processing Pipeline](artifacts/decisions/ADR-003-pure-boolean-state-graph-for-file-processing-pipeline.md) — 
- [ADR-004: Schema Refactor V1 — Graph Normalization](artifacts/decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — 
- [DD: Discovery Worker ERR 1579 Fix](artifacts/designs/pending/DD-discovery-worker-err1579-fix.md) — 
- [DD: File State Graph Completion](artifacts/designs/completed/DD-file-state-graph-completion.md) — 
- [DD: Schema Refactor V1](artifacts/designs/completed/DD-schema-refactor-v1.md) — 

---

## Scope

tests/unit/test_aql_safety.py, tests/unit/persistence/database/, nomarr/persistence/database/

---

## Problem Statement

The existing `tests/unit/test_aql_safety.py` provides static read-after-write detection on AQL strings but has three major blind spots:

1. **F-string AQL is invisible.** The AST extractor returns `None` for `JoinedStr` nodes containing `FormattedValue`, silently skipping ~32 f-string AQL calls across the persistence layer. This spans `vectors_track_aql.py` (9 sites), `library_files_aql/` (9 sites), `tags_aql/` (12 sites), `file_states_aql.py` (1 site), and `libraries_aql.py` (1 site). Many of these queries are assigned to a local variable first and then passed to `aql.execute()`, making them invisible to a visitor that only inspects inline f-string arguments.

2. **No collection name validation.** Typos in collection names (e.g., `file_has_states` instead of `file_has_state`) silently return empty results at runtime. No automated check compares AQL collection references against the canonical schema.

3. **No edge completeness enforcement.** Edge collections require `_from` and `_to` fields, but nothing verifies INSERT statements targeting edge collections include both fields.

Additionally, the persistence test infrastructure has two gaps:

4. **Duplicated mock fixtures.** Six test files in `tests/unit/persistence/database/` copy-paste an identical `mock_db` fixture (~8 lines each). No shared `conftest.py` exists. (Service-level test files also define `mock_db` fixtures, but those are structurally different and out of scope — see Constraints.)

5. **Zero test coverage on `VectorsTrackHotOperations` / `VectorsTrackColdOperations`.** These classes use dynamic collection names via f-strings and cannot be validated by static string extraction alone.

---

## Architecture

## Phase 1: F-String AQL Inventory Scan

### What It Does
Adds a new test to `tests/unit/test_aql_safety.py` that enumerates ALL f-string AQL calls (`ast.JoinedStr` nodes inside `aql.execute()` calls), extracts each interpolated expression, and validates it against an allowlist of known-safe patterns.

### Implementation Approach

**New AST visitor: `_FStringAqlVisitor` (with variable provenance tracking)**

- Walk all Python files under `nomarr/` (same scope as existing scan)
- For each `aql.execute()` call, resolve the first argument:
  - If the argument is an `ast.JoinedStr` → inspect it directly
  - If the argument is an `ast.Name` (variable reference) → trace it back through local assignments in the same function body to find the `ast.JoinedStr` it was assigned from. This handles the dominant pattern where queries are built as `query = f"""..."""` and then passed to `aql.execute(query)`.
- For each resolved `ast.JoinedStr`:
  - Extract each `ast.FormattedValue` node
  - Classify the interpolated expression against the safe pattern taxonomy below
  - Any interpolation NOT matching a safe pattern → violation

**Variable provenance resolution:**
The visitor must maintain a dict of `{var_name: ast_node}` for `ast.Assign` / `ast.AnnAssign` nodes within each function body. When `aql.execute(query)` references a name, look it up in this dict. Only single-assignment, same-function-scope resolution is needed — no cross-function or cross-module tracing. This covers the actual codebase patterns:
- `file_states_aql.py:902` (built) → `:941` (executed)
- `library_files_aql/crud.py:310` (built) → `:316` (executed)
- `tags_aql/queries.py:67` (built) → `:105` (executed)
- `tags_aql/mood.py:104` (built) → `:114` (executed)

**Safe interpolation taxonomy:**

| Pattern ID | Description | Example Variables | Classification |
|------------|-------------|-------------------|----------------|
| `collection_name` | Attribute access `self.collection_name` or local variable `collection_name` | `self.collection_name`, `collection_name` | Safe — dynamic vector collection |
| `integer_param` | Integer/float literal or typed-integer parameter | `nprobe`, `limit` | Safe — numeric value |
| `limit_clause` | Clause built from integer limit/offset | `limit_clause` (e.g., `f"LIMIT {limit}"`) | Safe — numeric derivation |
| `sort_clause` | Clause built from validated sort parameters | `sort_clause` (built from `order_by` list) | Safe — controlled construction |
| `filter_clause` | Filter built from validated field names and bind-var references | `filter_clause`, `filter_block`, `library_filter`, `library_filter_clause` | Safe — controlled string construction |
| `field_assignments` | Field assignment string built from dict keys | `field_assignments` (e.g., `", ".join(...)`) | Safe — controlled dict keys |
| `conditional_fragment` | Ternary or conditional AQL fragment (empty string or hardcoded sub-query) | `f"{'LET lib_match = ...' if library_id else ''}"` | Safe — hardcoded alternatives |
| `operator` | Operator from a safe map | `op` (e.g., `==`, `!=`, `IN`) | Safe — closed set |

**Concrete f-string sites found in research (32 total):**

| File | Line | Interpolation(s) | Classification | Execution |
|------|------|-------------------|----------------|-----------|
| `vectors_track_aql.py` | 82 | `{collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 205 | `{collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 248 | `{collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 291 | `{self.collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 415 | `{self.collection_name}` + `{nprobe}` | `collection_name` + `integer_param` | inline |
| `vectors_track_aql.py` | 471 | `{self.collection_name}` + `{nprobe}` | `collection_name` + `integer_param` | inline |
| `vectors_track_aql.py` | 503 | `{self.collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 529 | `{collection_name}` | `collection_name` | inline |
| `vectors_track_aql.py` | 572 | `{collection_name}` | `collection_name` | inline |
| `file_states_aql.py` | 902 | `{library_filter}` | `filter_clause` | var → :941 |
| `libraries_aql.py` | 157 | `{filter_clause}` | `filter_clause` | inline |
| `library_files_aql/crud.py` | 310 | `{field_assignments}` | `field_assignments` | var → :316 |
| `library_files_aql/queries.py` | 252 | `{filter_clause}` | `filter_clause` | var → :258 |
| `library_files_aql/queries.py` | 263 | `{filter_clause}` | `filter_clause` | var → :265 |
| `library_files_aql/queries.py` | 274 | `{filter_clause}` | `filter_clause` | var → :278 |
| `library_files_aql/queries.py` | 284 | `{filter_clause}` | `filter_clause` | var → :286 |
| `library_files_aql/queries.py` | 439 | `{filter_clause}` | `filter_clause` | inline |
| `library_files_aql/queries.py` | 457 | `{filter_clause}` | `filter_clause` | inline |
| `library_files_aql/tracks.py` | 53+57 | `{sort_clause}` + `{limit_clause}` | `sort_clause` + `limit_clause` | inline |
| `library_files_aql/tracks.py` | 105 | `{library_filter}` | `filter_clause` | var → :112 |
| `tags_aql/analytics.py` | 44 | `{conditional library_filter}` | `conditional_fragment` | var → :55 |
| `tags_aql/analytics.py` | 95 | `{conditional library_filter}` | `conditional_fragment` | var → :105 |
| `tags_aql/mood.py` | 104 | `{library_filter}` | `filter_clause` | var → :113 |
| `tags_aql/mood.py` | 232 | `{library_filter_clause}` | `filter_clause` | var → :249 |
| `tags_aql/mood.py` | 321 | `{library_filter_clause}` | `filter_clause` | var → :339 |
| `tags_aql/queries.py` | 67 | `{filter_block}` | `filter_clause` | var → :74 |
| `tags_aql/queries.py` | 86 | `{filter_block}` | `filter_clause` | var → :100 |
| `tags_aql/queries.py` | 130 | `{filter_block}` | `filter_clause` | var → :144 |
| `tags_aql/queries.py` | 288 | `{library_filter}` | `filter_clause` | var → :348 |
| `tags_aql/queries.py` | 348 | `{library_filter}` | `filter_clause` | var → :370 |
| `tags_aql/queries.py` | 358 | `{library_filter}` | `filter_clause` | var → :380 |
| `tags_aql/queries.py` | 412 | `{library_filter_clause}` | `filter_clause` | var → :430 |

**Key observation:** 21 of 32 sites use the variable-assignment pattern (built as `query = f"..."`, executed later as `aql.execute(query)`). A visitor that only inspects inline f-string arguments to `aql.execute()` would miss two-thirds of the codebase.

**Test function: `test_fstring_aql_interpolations_are_safe`**
- Collects all f-string AQL calls across codebase (with variable provenance resolution)
- Asserts every interpolation matches a safe pattern from the taxonomy
- Any new f-string AQL that doesn't match a known pattern will fail the test, forcing explicit review

### Files Touched
- `tests/unit/test_aql_safety.py` — add `_FStringAqlVisitor` class (with provenance tracking) and test function

### Acceptance Criteria
- Test passes on current codebase (all 32 f-string sites classified as safe)
- A new f-string AQL with `{user_input}` interpolation would fail the test
- Variable-assigned queries (e.g., `query = f"..."` → `aql.execute(query)`) are resolved and inspected
- Test output clearly identifies file, line, and interpolation expression for any violation

---

## Phase 2: Collection Name Whitelist Scan

### What It Does
Adds a test that extracts all literal collection names referenced in static AQL strings and validates them against a whitelist derived from migration files.

### Implementation Approach

**Collection extraction regexes** (extend existing `_RE_*` patterns):
```python
_RE_COLLECTION_REFS = re.compile(
    r'(?:'
    r'FOR\s+\w+\s+IN\s+(?!OUTBOUND|INBOUND|ANY|@)'  # FOR x IN coll
    r'|INSERT\s+.*?\bIN(?:TO)?\s+'                      # INSERT INTO coll
    r'|UPSERT\s+.*?\bIN(?:TO)?\s+'                       # UPSERT IN coll
    r'|REMOVE\s+.*?\bIN\s+'                               # REMOVE IN coll
    r'|(?:OUTBOUND|INBOUND|ANY)\s+(?:@\w+\s+)?'          # traversal edge coll
    r')'
    r'((?!@)\w+)',  # capture collection name (skip bind vars)
    re.IGNORECASE | re.DOTALL,
)
```

**Query resolution with variable provenance:**
The `_scan_aql_execute_calls` helper must be enhanced to resolve variable-assigned queries, not just inline string literals. When `aql.execute(query)` references a name, trace back through local assignments to find the string (or f-string) value. This is the same provenance resolution described in Phase 1. Phases 2 and 3 share this enhanced resolver.

**Sub-scan: Bind-var constant resolution for `@@collection` patterns**

Files like `navidrome_playcounts_aql.py` and `navidrome_tracks_aql.py` use module-level constants passed as `@@collection` bind vars instead of literal collection names in AQL strings:
```python
_PLAYCOUNTS = "navidrome_playcounts"
_HAS_PLAYS = "has_plays"
_TRACKS = "navidrome_tracks"
_HAS_ND_ID = "has_nd_id"
```
These are invisible to the collection-extraction regex (which skips `@`-prefixed references by design).

Add a supplementary scan:
1. In each `aql.execute()` call, inspect `bind_vars` keyword argument for keys starting with `@` (the `@@collection` pattern surfaces as `"@collection": value` in Python)
2. Resolve the value — if it's a `ast.Name` referencing a module-level constant, look up that constant's string value
3. Validate the resolved collection name against `DOCUMENT_COLLECTIONS | EDGE_COLLECTIONS`

This can be a separate test function (`test_bind_var_collection_names_are_valid`) or folded into `test_aql_collection_names_are_valid` as a second pass.

**Canonical whitelist (25 document + 13 edge = 38 static collections):**

Document collections:
```python
DOCUMENT_COLLECTIONS = {
    "applied_migrations", "calibration_history", "calibration_state",
    "file_states", "health", "libraries", "library_files", "library_folders",
    "library_pipeline_states", "library_scans", "locks", "meta",
    "ml_capacity_estimates", "ml_capacity_probe_locks", "ml_model_outputs",
    "ml_models", "navidrome_playcounts", "navidrome_tracks",
    "segment_scores_stats", "sessions", "tags", "vector_promotion_locks",
    "vram_promises", "worker_claims", "worker_restart_policy",
}
```

Edge collections:
```python
EDGE_COLLECTIONS = {
    "file_has_state", "file_has_segment_stats", "file_has_vectors",
    "has_nd_id", "has_plays", "library_contains_file",
    "library_contains_folder", "library_has_pipeline_state",
    "library_has_scan", "model_has_calibration", "model_has_output",
    "song_has_tags", "tag_model_output",
}
```

**Dynamic collection exclusion:**
```python
_RE_DYNAMIC_COLLECTION = re.compile(r'^vectors_track_(hot|cold)__')
```

**Test function: `test_aql_collection_names_are_valid`**
- Scan all AQL strings via enhanced `_scan_aql_execute_calls` (with variable provenance resolution)
- Extract collection name references via regex from resolved query strings
- Skip bind variables (`@coll`, `@@coll`)
- Skip dynamic collections matching `vectors_track_(hot|cold)__*`
- Assert every remaining collection name is in `DOCUMENT_COLLECTIONS | EDGE_COLLECTIONS`
- Additionally, resolve `@@collection` bind-var values from module-level constants and validate those against the whitelist

### Files Touched
- `tests/unit/test_aql_safety.py` — add whitelist constants and test function

### Acceptance Criteria
- Test passes on current codebase
- A typo like `file_has_states` would be flagged
- Adding a new collection requires updating migration AND whitelist (fail-fast on drift)

---

## Phase 3: Edge INSERT Completeness Scan

### What It Does
Adds a test that verifies every `INSERT` statement targeting a known edge collection includes both `_from` and `_to` fields.

### Implementation Approach

**Detection logic:**
1. For each AQL string (resolved via enhanced `_scan_aql_execute_calls` with variable provenance), find `INSERT { ... } INTO <collection>` patterns
2. If `<collection>` is in `EDGE_COLLECTIONS`, extract the dict literal
3. Assert both `_from` and `_to` appear as keys in the dict literal
4. Also check `UPSERT { ... } INSERT { ... } IN <edge_collection>` — the INSERT portion must have `_from`/`_to`

**Regex approach:**
```python
_RE_INSERT_EDGE = re.compile(
    r'INSERT\s+\{([^}]+)\}\s+IN(?:TO)?\s+(\w+)',
    re.IGNORECASE | re.DOTALL,
)
```
For each match: if group(2) is in `EDGE_COLLECTIONS`, verify `_from` and `_to` appear in group(1).

**Known edge collections for enforcement:**
```python
EDGE_COLLECTIONS  # same set as Phase 2
```

**Note:** This scan only covers static AQL strings. The f-string AQL in `vectors_track_aql.py` targets `file_has_vectors` with static `_from`/`_to` bind vars — those are already safe but invisible to this scan. Phase 5's SchemaAwareMockDB covers that gap.

**Test function: `test_edge_inserts_have_from_and_to`**

### Files Touched
- `tests/unit/test_aql_safety.py` — add test function (reuses whitelist from Phase 2)

### Acceptance Criteria
- Test passes on current codebase (all current edge INSERTs have `_from`/`_to`)
- An `INSERT { _from: @x } INTO file_has_state` missing `_to` would fail
- UPSERT patterns with edge collections also validated

---

## Phase 4: Shared conftest.py Extraction

### What It Does
Creates `tests/unit/persistence/database/conftest.py` with shared fixtures, then migrates all 6 existing test files to use them. Purely mechanical — no behavior changes.

### Implementation Approach

**New file: `tests/unit/persistence/database/conftest.py`**
```python
from unittest.mock import MagicMock
import pytest

@pytest.fixture
def mock_db() -> MagicMock:
    """Provide mock ArangoDB database handle."""
    db = MagicMock()
    db.name = "test_db"
    return db
```

**Migration steps for each of 6 test files:**
1. Remove the local `mock_db` fixture definition
2. The `ops` fixture remains in each file (it's specific to the operations class under test)
3. Verify tests still pass — pytest auto-discovers conftest fixtures

**Files affected:**
- `tests/unit/persistence/database/conftest.py` — CREATE
- `tests/unit/persistence/database/test_file_states_aql.py` — remove mock_db fixture
- `tests/unit/persistence/database/test_library_pipeline_states_aql.py` — remove mock_db fixture
- `tests/unit/persistence/database/test_library_scans_aql.py` — remove mock_db fixture
- `tests/unit/persistence/database/test_navidrome_playcounts_aql.py` — remove mock_db fixture
- `tests/unit/persistence/database/test_vram_promises_aql.py` — remove mock_db fixture
- `tests/unit/persistence/database/test_worker_restart_policy_aql.py` — remove mock_db fixture

**Out of scope:** Service-level test files (`test_worker_system_svc_restart.py`, `test_pipeline_svc.py`, `test_file_watcher_svc.py`, `test_discovery_worker_deferred_writes.py`) also define `mock_db` fixtures, but those are structurally different (e.g., `test_file_watcher_svc.py` takes a `temp_library` parameter). They are not part of this deduplication.

### Acceptance Criteria
- No test file under `tests/unit/persistence/database/` defines its own `mock_db` fixture
- All existing tests pass unchanged
- `conftest.py` is the single source of truth for the `mock_db` fixture in the persistence/database test directory
- Service-level `mock_db` fixtures remain untouched (explicitly out of scope)

---

## Phase 5: Schema-Aware MockDB (Optional / Phase 2)

### What It Does
Creates a `SchemaAwareMockDB` test utility that wraps `MagicMock` and intercepts `aql.execute()` calls to provide runtime validation of:
- Collection name against whitelist
- Edge INSERT completeness (`_from`/`_to` presence)
- `_from`/`_to` vertex collection format matching graph edge definitions

### Implementation Approach

**New file: `tests/unit/persistence/database/schema_aware_mock.py`**

```python
class SchemaAwareMockDB:
    """MagicMock wrapper that validates AQL against schema constraints."""
    
    # Schema derived from V001/V021/V023 migrations
    VALID_COLLECTIONS = DOCUMENT_COLLECTIONS | EDGE_COLLECTIONS  # from Phase 2
    EDGE_DEFINITIONS = {
        "file_has_state": {"from": ["library_files"], "to": ["file_states"]},
        "file_has_vectors": {"from": ["library_files"], "to": ["vectors_track_hot", "vectors_track_cold"]},
        "file_has_segment_stats": {"from": ["library_files"], "to": ["segment_scores_stats"]},
        "library_contains_file": {"from": ["libraries"], "to": ["library_files"]},
        "library_contains_folder": {"from": ["libraries"], "to": ["library_folders"]},
        "library_has_scan": {"from": ["libraries"], "to": ["library_scans"]},
        "library_has_pipeline_state": {"from": ["libraries"], "to": ["library_pipeline_states"]},
        "has_nd_id": {"from": ["navidrome_tracks"], "to": ["library_files"]},
        "has_plays": {"from": ["navidrome_tracks"], "to": ["navidrome_playcounts"]},
        "song_has_tags": {"from": ["library_files"], "to": ["tags"]},
        "model_has_output": {"from": ["ml_models"], "to": ["ml_model_outputs"]},
        "model_has_calibration": {"from": ["ml_models"], "to": ["calibration_state"]},
        "tag_model_output": {"from": ["tags"], "to": ["ml_model_outputs"]},
    }
```

**Validation on `aql.execute()` interception:**
1. Parse the AQL string (regex, not full parser)
2. Extract collection references → validate against whitelist (allow dynamic `vectors_track_*`)
3. If INSERT/UPSERT targets an edge collection and `bind_vars` are provided, check `_from`/`_to` keys exist in bind_vars
4. If `_from`/`_to` values are present, validate vertex collection prefix matches graph edge definitions

**Primary use case:** Testing `VectorsTrackHotOperations` and `VectorsTrackColdOperations` — the classes with zero test coverage that use dynamic collection names.

**Add to conftest.py:**
```python
@pytest.fixture
def schema_mock_db() -> SchemaAwareMockDB:
    """Provide schema-validating mock ArangoDB."""
    return SchemaAwareMockDB()
```

### Files Touched
- `tests/unit/persistence/database/schema_aware_mock.py` — CREATE
- `tests/unit/persistence/database/conftest.py` — add `schema_mock_db` fixture
- `tests/unit/persistence/database/test_vectors_track_aql.py` — CREATE (new test file for VectorsTrack* classes)

### Acceptance Criteria
- `SchemaAwareMockDB` raises `AssertionError` when AQL references unknown collection
- `SchemaAwareMockDB` raises `AssertionError` when edge INSERT missing `_from`/`_to`
- Basic test coverage exists for `VectorsTrackHotOperations.upsert_vector` and `.delete_by_file_id`
- Basic test coverage exists for `VectorsTrackColdOperations.search_similar`

### Priority Note
This phase is OPTIONAL and lower priority than Phases 1–4. Static AST scans (Phases 1–3) cover the majority of the safety surface. Phase 5 adds runtime validation where static analysis cannot reach (dynamic collection names, bind_var content). Implement only after Phases 1–4 are complete and validated.

---

## Design Goals

1. **Eliminate blind spots** in AQL safety testing — every `aql.execute()` call in the persistence layer should be validated by at least one scan.
2. **Catch typos early** — collection name misspellings should fail in CI, not silently return empty results in production.
3. **Enforce schema contracts** — edge collections must always receive properly-formed edge documents.
4. **Reduce fixture duplication** — single source of truth for mock_db, extensible for schema-aware testing.
5. **Enable VectorsTrack testing** — provide infrastructure to test the most complex, currently untested persistence module.

---

## Constraints

- **Forward-only migrations** (ADR-003, ADR-004): Schema whitelist must reflect cumulative state of V001+V021+V023. No rollback paths.
- **Dynamic vector collections are architectural, not bugs** (ADR-004): The f-string scan must explicitly accommodate `vectors_track_(hot|cold)__*` patterns as safe, not flag them.
- **Static AST scans first** (rnd-manager L24): PhaseS 1–3 are the primary safety mechanism. Phase 5 (SchemaAwareMockDB) is secondary — only where static can't reach.
- **No full AQL parsing** (DD-discovery-worker-err1579-fix): Use regex on AQL strings, not grammar-based parsing. The existing test already establishes this pattern.
- **Conftest extraction is mechanical** (Phase 4): No behavior changes to existing tests. Pure deduplication.
- **file_has_state is a singleton boolean axis graph** (ADR-003): Edge completeness checks must account for this — no payload on state edges, _from/_to only.
- **FileStatesOperations is canonical owner** for state transitions — tests should not duplicate transition logic.
- **Existing test_aql_safety.py structure preserved**: New scans extend the existing file, preserving its AST walker infrastructure and code organization patterns.
- **Service-level `mock_db` fixtures are out of scope**: `test_worker_system_svc_restart.py`, `test_pipeline_svc.py`, `test_file_watcher_svc.py`, and `test_discovery_worker_deferred_writes.py` define structurally different `mock_db` fixtures (e.g., accepting `temp_library` parameters). These are service-specific and not candidates for the Phase 4 conftest extraction.
- **Bind-var collection references must be validated**: Module-level constants used as `@@collection` bind-var values (e.g., `_TRACKS`, `_HAS_ND_ID` in navidrome modules) are not visible in AQL string regex. Phase 2 includes a supplementary scan to resolve these constants and validate them against the whitelist.

---

## Open Questions

1. **Should the collection whitelist be auto-derived from migration files at test time, or maintained as a static constant?** Static is simpler and catches drift earlier (migration changes without whitelist update → test fail). Auto-derive is more DRY but could mask drift. Recommendation: static constant with a comment pointing to source migrations.

2. **Should f-string safe patterns require same-function-scope provenance verification?** The current design classifies interpolated variables by name against a taxonomy of 8 pattern types (see Phase 1 table). A stricter approach would trace each variable's assignment within the same function body and verify the constructed value is safe. Recommendation: classify by name for now — the taxonomy is comprehensive (covers all 32 current sites) and manually reviewed. Add provenance verification as a follow-up if the f-string site count grows significantly.

3. **Should Phase 5 SchemaAwareMockDB validate bind_var types (e.g., _from must be string starting with vertex collection)?** This adds value but increases complexity. Recommendation: start with key-presence checks, add type validation as a follow-up if needed.

4. **Should the scan scope include `scripts/` directory?** The existing scan covers `nomarr/` only. Scripts contain some AQL but are not production code. Recommendation: keep scope as `nomarr/` for now — scripts can be added later.

---
