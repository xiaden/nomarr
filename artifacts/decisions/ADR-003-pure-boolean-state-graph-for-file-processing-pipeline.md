# ADR-003: Pure Boolean State Graph for File Processing Pipeline

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** persistence, arangodb, file-states, architecture  
**Source Log:** exec-director#L1  

## Context

The file processing pipeline tracked file state (tagged, calibrated, scanned, reconciled, errored) via edges in a `file_has_state` graph, but the implementation was half-complete: only positive states existed (no negative vertices), state queries required expensive full-collection scans, edge payloads carried domain data that belonged elsewhere, and "reconciled" conflated two independent concerns (tags written to disk vs tags current with model). Several persistence mixins (`calibration.py`, `status.py`) were pure passthroughs adding no value.

## Decision

Adopt a pure boolean state model with 8 axes, each having positive and negative singleton vertices in `file_states`:

- tagged/not_tagged, too_short/not_too_short, calibrated/not_calibrated
- tags_written/tags_not_written, tags_current/tags_stale
- scanned/not_scanned, vectors_extracted/not_vectors_extracted, errored/not_errored

Key design choices:

1. **Every file has exactly one edge per axis** (invariant enforced by REMOVE+INSERT transitions)
2. **Zero payload on edges** — all domain data lives on documents or in separate collections
3. **Negative vertices enable O(1) discovery** via INBOUND traversal (vs old O(n) scans)
4. **"Reconciled" split** into two independent axes: tags_written/tags_not_written (disk state) and tags_current/tags_stale (model freshness)
5. **too_short is a proper boolean axis** with set_too_short/set_not_too_short like all others
6. **Library-scoped queries use set intersection** via OUTBOUND library_contains_file + INTERSECTION()
7. **Edge payloads dropped entirely** — alpha policy allows breaking changes, no migration of old payload data
8. **has_nomarr_namespace dropped** (YAGNI — write-only, never read)
9. **write_mode stays on libraries doc** (not file-level)

## Consequences

**Positive:**

- Discovery queries O(1) instead of O(n) — INBOUND traversal on negative vertex finds files needing work
- Clean separation of concerns — state edges are program logic, domain data lives elsewhere
- Passthrough mixins eliminated — fewer layers, clearer call chains
- Method signatures simplified — no more calibration_hash, target_mode, write_mode params threading through layers

**Negative:**

- Migration V022 required (forward-only, seeds negative vertices for all existing files)
- All callers updated (17 files across components/workflows/services/interfaces)
- `count_recently_tagged` metric lost — tagged_at timestamp was on old edge payload, data not preserved
- Test suite needs significant updates (23+ test files reference old API)

**Deferred:**

- Domain relationship edges (genre_of, artist_of) — separate concern, separate ADR when needed
- calibration_snapshots collection — deferred to model versioning work

## References

- DD: artifacts/designs/pending/DD-file-state-graph-completion.md
- Plans: TASK-file-state-graph-{A,B,C,D} in artifacts/plans/pending/
- Contracts: artifacts/designs/parts/file-state-graph/CONTRACTS.md
