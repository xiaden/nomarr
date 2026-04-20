# Task: File State Graph Migration (V022)

## Problem Statement

The `file_has_state` edge model carries legacy payload attributes (`version`, `hash`, `mode`, `tagged_at`, `calibrated_at`, `calibration_hash`, `written_at`, `has_namespace`) that violate the new pure-boolean state design. Two vertices need renaming (`ml_tagged` → `tagged`) or splitting (`reconciled` → `tags_written` + `tags_current`). New negative state vertices (`not_tagged`, `not_too_short`, etc.) must exist so INBOUND traversal discovery works. Files without edges on any axis need negative-state edges seeded.

This plan creates `nomarr/migrations/V022_file_state_graph_completion.py` — a forward-only, idempotent migration that transforms existing data to match the new state graph model defined in `DD-file-state-graph-completion.md`.

**Prerequisite:** None (independent of Plan A — uses hardcoded vertex strings, not imported constants)

## Phases

### Phase 1: Create migration file with DDL and vertex seeding

- [x] Create `nomarr/migrations/V022_file_state_graph_completion.py` with required metadata: `MIGRATION_VERSION = "0.2.2"`, `DESCRIPTION`, and `upgrade(db: DatabaseLike)` signature following the pattern in V021
    **V022created:** Created V022_file_state_graph_completion.py with MIGRATION_VERSION="0.2.2", DESCRIPTION, upgrade(db) signature, future annotations, TYPE_CHECKING guard, logging. Follows V021 pattern exactly.
- [x] Implement vertex seeding: insert all new `file_states` vertices using `db.collection("file_states").get(key)` guard + `contextlib.suppress(DocumentInsertError)` pattern — vertices to seed: `tagged`, `not_tagged`, `not_too_short`, `not_calibrated`, `tags_written`, `tags_not_written`, `tags_current`, `tags_stale`, `not_scanned`, `not_vectors_extracted`, `not_errored`
    **VertexSeeding:** Seeds 11 vertices using get() guard + contextlib.suppress(DocumentInsertError) pattern. Vertices already existing from V001/V021 (e.g. tags_written) are safely skipped by the guard.
- [x] Implement index verification: ensure persistent index on `file_has_state._to` and unique persistent index on `file_has_state.[_from, _to]` using `coll.add_persistent_index()` wrapped in `contextlib.suppress(IndexCreateError)`
    **IndexVerify:** Added persistent index on file_has_state._to and unique persistent index on [_from, _to], both wrapped in contextlib.suppress(IndexCreateError).
  **Notes:** Vertices `calibrated`, `ml_tagged`, `reconciled`, `scanned`, `too_short`, `vectors_extracted`, `tags_written`, `errored` already exist from V001/V021 — the guard pattern makes this safe. The `tags_written` vertex was seeded by V021 with different semantics but same key, so it already exists.

### Phase 2: Implement edge repointing and splitting

- [x] Implement `ml_tagged` → `tagged` repoint: AQL that iterates `file_has_state` edges where `_to == "file_states/ml_tagged"`, REMOVEs each edge, and INSERTs replacement with `_to = "file_states/tagged"` using `OPTIONS { ignoreErrors: true }`
    **EdgeRepoint:** AQL iterates file_has_state edges where _to == "file_states/ml_tagged", REMOVEs each, INSERTs replacement with_to = "file_states/tagged" using OPTIONS { ignoreErrors: true }. Logs count of repointed edges.
- [x] Implement `reconciled` → `tags_written` + `tags_current` split: AQL that iterates edges where `_to == "file_states/reconciled"`, REMOVEs each, INSERTs two new edges (`tags_written` and `tags_current`) using `OPTIONS { ignoreErrors: true }` — `mode` and `has_namespace` attributes are intentionally dropped
    **EdgeSplit:** AQL iterates file_has_state edges where _to == "file_states/reconciled", REMOVEs each, INSERTs two new edges (tags_written and tags_current) using OPTIONS { ignoreErrors: true }. mode/has_namespace attributes intentionally dropped. Logs count of split edges.
  **Warning:** The `reconciled` → `tags_written` + `tags_current` conversion means files that had `reconciled` state get BOTH `tags_written` AND `tags_current`. This is correct: a reconciled file had its tags written and they were current at the time.

### Phase 3: Strip payload attributes from edges

- [x] Implement payload stripping: AQL UPDATE that finds all `file_has_state` edges with any non-null payload attribute (`version`, `hash`, `mode`, `tagged_at`, `calibrated_at`, `calibration_hash`, `written_at`, `has_namespace`) and sets them all to `null` using `OPTIONS { keepNull: false }` to physically remove the attributes
    **PayloadStrip:** **PayloadStrip:** AQL UPDATE with FILTER checking all 8 payload attributes for non-null, sets all to null with OPTIONS { keepNull: false } to physically remove. Logs count of stripped edges. Runs after Phase 2 so repointed/split edges are not redundantly processed.
  **Notes:** This runs after Phase 2 so that edges created by repoint/split (which are already clean) are not redundantly processed. The FILTER ensures only edges with leftover attributes are touched.

### Phase 4: Seed negative states for existing files

- [x] Implement negative state seeding: for each of the 8 state axes, run an AQL query that finds all `library_files` documents that have NO edge to either the positive or negative vertex of that axis, and INSERTs an edge to the negative vertex with `OPTIONS { ignoreErrors: true }`
    **NegativeSeeding:** Loops over 8 state axes, runs AQL per axis that finds library_files with no edge to positive or negative vertex, inserts edge to negative vertex with OPTIONS { ignoreErrors: true }. Uses bind_vars for vertex IDs. Logs count per axis.
  **Notes:** The 8 axes with their (positive, negative) pairs are: (`tagged`, `not_tagged`), (`too_short`, `not_too_short`), (`calibrated`, `not_calibrated`), (`tags_written`, `tags_not_written`), (`tags_current`, `tags_stale`), (`scanned`, `not_scanned`), (`vectors_extracted`, `not_vectors_extracted`), (`errored`, `not_errored`). Use bind variables `@positive` and `@negative` with the full vertex IDs (e.g. `"file_states/tagged"`, `"file_states/not_tagged"`). Log the count of inserted edges per axis.

### Phase 5: Verification logging

- [x] Add verification logging at end of `upgrade()`: log total count of `file_has_state` edges, count of edges per distinct `_to` value, and count of edges still carrying any payload attributes (should be 0)
    **VerificationLogging:** Added 3 AQL queries at end of upgrade(): (1) total file_has_state edge count, (2) edges grouped by _to with per-target log lines, (3) residual payload attribute count (expected 0). All informational via logger.info(), no exceptions raised on mismatch.
  **Notes:** Verification is informational only — does not raise on mismatch. Useful for operator confidence in production runs.

### Phase 6: Lint and validate

- [x] Run `lint_project_backend` and confirm zero errors in `nomarr/migrations/V022_file_state_graph_completion.py`
    **LintClean:** lint_project_backend found 0 errors in V022_file_state_graph_completion.py. All 18 reported errors are pre-existing in library_files_aql/ files (attr-defined, call-arg, no-any-return) — not blockers.
- [x] Run `plan_read("TASK-file-state-graph-B-migration")` to validate this plan parses correctly
    **PlanValid:** plan_read parsed successfully. All 10 steps across 6 phases visible. Phases 1-5 complete, Phase 6 now complete. Plan structure valid with annotations, notes, and warnings intact.

## Completion Criteria

- `nomarr/migrations/V022_file_state_graph_completion.py` exists with valid metadata and `upgrade()` function
- Migration seeds all 11 new state vertices (idempotent)
- Migration verifies indexes on `file_has_state._to` and `file_has_state._from,_to`
- Migration repoints `ml_tagged` edges to `tagged`
- Migration splits `reconciled` edges into `tags_written` + `tags_current` (dropping `mode`/`has_namespace`)
- Migration strips all payload attributes from `file_has_state` edges
- Migration seeds negative state edges for all files missing axis coverage
- All AQL operations use `ignoreErrors: true` or conditional guards for idempotency
- Migration uses hardcoded vertex name strings (not imports from `file_states_aql.py`)
- `lint_project_backend` passes with zero errors

## References

- Design doc: `artifacts/designs/pending/DD-file-state-graph-completion.md` (Migration section)
- Parts breakdown: `artifacts/designs/parts/file-state-graph/README.md`
- Migration guide: `docs/dev/migrations.md`
- V021 pattern reference: `nomarr/migrations/V021_schema_refactor_v1.py`
- V001 baseline (original file_states): `nomarr/migrations/V001_baseline.py`
