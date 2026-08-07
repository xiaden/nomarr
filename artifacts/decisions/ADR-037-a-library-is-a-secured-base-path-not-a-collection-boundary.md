# ADR-037: A Library Is a Secured Base Path, Not a Collection Boundary

**Status:** Accepted  
**Date:** 2026-06-19  
**Tags:** architecture, data-model, conceptual-clarity, libraries  

## Context

The term "library" in Nomarr has been overloaded and poorly defined since the application's inception. This ambiguity caused real architectural damage — most notably, the per-library vector store design (now rejected by ADR-036), which assumed libraries required data isolation as if they were multi-tenant boundaries.

Currently, a library in Nomarr is:
- A base folder path on the filesystem that the user has authorized Nomarr to scan
- A library record in the database with metadata (name, path, auto-write settings, etc.)
- The anchor for `library_contains_file` edges, linking scanned files back to their origin path

What a library is **not**:
- A collection of files in any active sense — Nomarr does not curate, copy, or own files; it scans and indexes them
- A tenant boundary — Nomarr is a single-user application; libraries do not isolate data between users
- A meaningful scope for ML operations — vector stores, calibration, and tag inference all operate on the union of files regardless of library membership

The confusion stems from the word itself. "Library" in media software (Plex, Jellyfin, iTunes) implies a managed catalog — curated, browsable, with its own views and policies. Nomarr's "libraries" are closer to "watched folders" or "scan roots" — they answer the question "where should I look for audio files?" rather than "what belongs in this collection?"

## Decision

A Library in Nomarr is formally defined as:

**A secured base path the user has authorized Nomarr to recursively scan for audio files.**

Its operational role is limited to three things:

1. **Authorization gate** — Nomarr will not scan, process, or index files outside of paths registered as libraries. The library path is the security boundary.

2. **Provenance tracking** — Files are linked back to their library via `library_contains_file` edges. This enables path reconciliation (detecting moves/deletes), path re-basing (if a library root changes), and library-scoped queries when the caller explicitly needs to filter by origin.

3. **User-facing metadata** — The library document carries a human-readable name and per-library configuration (auto-write, pipeline state), giving users a handle for the path they registered.

What a library does **not** define:

- **Data isolation** — No data is stored per-library except the library document itself. All file data (`library_files`, `song_has_tags`, vectors, calibration state) lives in global collections. The `library_contains_file` edge provides optional filtering, not mandatory scoping.

- **Processing batch** — ML processing, vector persistence, and pipeline stages are not scoped per-library. Workers discover work globally and process whatever needs processing. The pipeline state graph tracks per-library progress for UX purposes, but the underlying operations are global.

- **Vector search scope** — Per ADR-036, vector stores are per-backbone with no library boundary. ANN search inherently returns results across all libraries.

- **Calibration scope** — Per ADR-004 and DD-ml-pipeline-automation, calibration is global. One calibration applies to all files regardless of library membership.

**Naming note:** The term "library" is retained for backward compatibility in the codebase and API, but internal documentation and future design work should treat "library" as synonymous with "scan root" or "authorized base path." No rename is planned — the cost of API and schema migration outweighs the conceptual clarity gain.

## Consequences

**Clarity gains:**

1. **Eliminates isolation-by-default thinking** — Future designs start from the correct baseline: all data is global unless there's a concrete reason to scope it. Library membership is a filter, not a boundary.
2. **Validates ADR-036** — The per-library vector store was wrong because it assumed libraries were isolation domains. This ADR makes that reasoning explicit and reusable.
3. **Guards against future boundary-itis** — Any proposal adding per-library storage must now justify itself against this definition. "Because they're separate libraries" is not sufficient.

**Implementation impact:**

No code changes. This ADR is a conceptual clarification, not a refactor. The `library_contains_file` edge, library documents, and pipeline state graph are correct infrastructure — they just need to be understood as optional provenance and UX mechanisms, not data boundaries.

**Downstream effects:**

- Future work (e.g., segmented vector streams) builds on the global-default baseline
- Multi-library users get cross-library results by default — which is what they expect (their music is their music, regardless of which folder it lives in)
- The word "library" remains an imperfect term, but the concept is now formally documented

## References

- ADR-036 — Vector Stores Are Per-Backbone, Not Per-Backbone-Per-Library (supersedes per-library vector isolation)
- ADR-003 — Pure Boolean State Graph for File Processing Pipeline (file-level state tracking)
- ADR-004 — Schema Refactor V1 — Graph Normalization and Collection Decomposition (global collections)
- DD-ml-pipeline-automation — per-library state graph for UX, global calibration for data
