# ADR-008: Two-Phase Tag Curation — Deferred File Writeback

**Status:** Accepted (Revised)  
**Date:** 2026-04-04  
**Tags:** persistence, tag-editor, performance, file-writeback  
**Source Log:** rnd-manager#L1  
**Revised:** 2026-04-04 — Changed from "never write to files" to two-phase curation→commit with deferred writeback

## Context

Tag edits in the Tag Editor could follow several strategies:

1. **DB-only (original ADR-008):** Write tag changes to ArangoDB only. Fast, no I/O, no file locking. But tag edits are never visible to external players, and users have no path to persist changes to disk.
2. **Immediate writeback:** Write to DB and audio files synchronously. Ensures external players see changes but introduces file I/O, locking, format-specific writers, and risk of corruption on every edit.
3. **Two-phase curation → commit:** Curation operations are instant DB-only changes. File writeback is deferred and user-initiated via a "Commit Changes" action, batching multiple edits into a single file write pass.

The original ADR-008 chose option 1 (DB-only, never write to files). This was appropriate as a conservative starting point, but the design has matured: ADR-003's boolean state graph already provides the `tags_written/tags_not_written` axis specifically designed to track files with pending tag changes. The infrastructure for deferred writeback exists — the decision is about when and how to use it.

## Decision

Two-phase curation → commit. Curation operations are instant DB-only changes that set `tags_not_written` state (per ADR-003 boolean state graph). File writeback is deferred and user-initiated via a "Commit Changes" action.

**Phase 1 — Curation (instant, DB-only):**

- All tag curation operations (rename, merge, split, single-song edit) write to ArangoDB only
- Affected files are transitioned to `tags_not_written` state via ADR-003's state graph
- No file I/O, no locking — sub-second response times for all curation operations
- The UI shows a persistent indicator of uncommitted changes (e.g., "12 files with pending tag changes")

**Phase 2 — Commit (user-initiated, batched file writeback):**

- User explicitly triggers "Commit Changes" to write pending tag edits to audio files on disk
- Writeback processes all files in `tags_not_written` state
- On successful write, files transition to `tags_written` state
- Failures are reported per-file without blocking other files
- Commit is idempotent — can be retried safely

**Key properties:**

- Curation and commit are fully decoupled — users can curate for hours before committing
- Commit scope can be filtered (e.g., commit only selected files, or all pending)
- If a user never commits, behavior is identical to the original DB-only ADR-008
- Re-scan awareness: scan pipeline must respect `tags_not_written` state to avoid overwriting uncommitted edits

## Consequences

**Positive:**

- Curation operations remain fast (DB round-trip only, no file I/O)
- Users get a path to persist tag changes to disk for external player compatibility
- Batched writeback is more efficient than per-edit writes
- ADR-003's `tags_not_written` state provides built-in tracking — no new infrastructure
- Graceful degradation: uncommitted changes are still visible within Nomarr

**Negative:**

- Commit phase requires audio format writers (mutagen or equivalent) — added dependency
- File writeback introduces I/O failure modes (permissions, corrupt files, unsupported formats)
- UI must clearly communicate the two-phase model to avoid confusion
- Re-scan must be tag-merge-aware to avoid overwriting pending edits

**Risks:**

- Users may not understand the two-phase model. Clear UI messaging required ("12 files have uncommitted tag changes — Commit to save to disk")
- Large commit batches (thousands of files) may need progress reporting and cancellation

## References

DD-tag-editor.md, ADR-003 (boolean state graph — `tags_written/tags_not_written` axis)
