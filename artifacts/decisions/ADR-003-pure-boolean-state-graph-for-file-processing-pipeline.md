# ADR-003: Pure Boolean State Graph for File Processing Pipeline

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** persistence, arangodb, file-states, architecture  
**Source Log:** exec-director#L1  

## Context

The file processing pipeline tracked file state (tagged, calibrated, scanned, reconciled, errored) via rows in a `file_has_state` join table, but the implementation was half-complete: only positive states existed (no negative states), state queries required expensive full-table scans, state rows carried domain data that belonged elsewhere, and "reconciled" conflated two independent concerns (tags written to disk vs tags current with model). Several persistence mixins (`calibration.py`, `status.py`) were pure passthroughs adding no value.

## Decision

Adopt a pure boolean state model with 8 axes, each having positive and negative singleton rows in `file_states`:

- tagged/not_tagged, calibrated/not_calibrated
- tags_written/tags_not_written, tags_current/tags_not_fresh
- tags_extracted/tags_not_extracted, scanned/not_scanned
- vectors_extracted/not_vectors_extracted, errored/not_errored

Key design choices:

1. **Every file has exactly one state row per axis** (invariant enforced by delete+insert transitions)
2. **Zero payload on state rows** — all domain data lives on the file's primary row or in separate tables
3. **Negative states enable O(1) discovery** via indexed FK queries (vs old O(n) scans)
4. **"Reconciled" split** into two independent axes: tags_written/tags_not_written (disk state) and tags_current/tags_not_fresh (model freshness)
5. **Negative poles always use `not_` prefix** for consistency (tags_not_fresh, tags_not_extracted)
6. **Library-scoped queries use set intersection** via a library_contains_file join table + INTERSECT
7. **State-row payloads dropped entirely** — alpha policy allows breaking changes, no migration of old payload data
8. **has_nomarr_namespace dropped** (YAGNI — write-only, never read)
9. **write_mode stays on libraries doc** (not file-level)

## Consequences

**Positive:**

- Discovery queries O(1) instead of O(n) — indexed FK lookup on a negative state finds files needing work
- Clean separation of concerns — state rows are program logic, domain data lives elsewhere
- Passthrough mixins eliminated — fewer layers, clearer call chains
- Method signatures simplified — no more calibration_hash, target_mode, write_mode params threading through layers

**Negative:**

- Migration V022 required (forward-only, seeds negative states for all existing files)
- All callers updated (17 files across components/workflows/services/interfaces)
- `count_recently_tagged` metric lost — tagged_at timestamp was on the old state-row payload, data not preserved
- Test suite needs significant updates (23+ test files reference old API)

**Deferred:**

- Domain relationship edges (genre_of, artist_of) — separate concern, separate ADR when needed
- calibration_snapshots table — deferred to model versioning work

## References

- DD: artifacts/designs/archive/DD-file-state-graph-completion.md
- Plans: TASK-file-state-graph-{A,B,C,D} in artifacts/plans/pending/
- Contracts: artifacts/designs/parts/file-state-graph/CONTRACTS.md

**Note:** The `Plans:` and `Contracts:` entries above are historical planning references — the TASK-file-state-graph-{A,B,C,D} plan files and the file-state-graph contracts directory no longer exist in the corpus. This ADR is the surviving record of that decision.
