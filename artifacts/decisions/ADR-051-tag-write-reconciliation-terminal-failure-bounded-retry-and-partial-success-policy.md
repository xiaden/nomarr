# ADR-051: Tag-write reconciliation terminal-failure, bounded-retry, and partial-success policy

**Status:** Accepted  
**Date:** 2026-09-15  
**Tags:** background-tasks, tag-write, reconciliation, partial-success  
**Source Log:** nyx#L55  

## Context

A library tag-write run can remain permanently `running` when even one pending file has a persistent write failure: every per-file failure path releases the reconciliation claim but never advances the song state, so the song stays in `tags_not_fresh`/`not_written`; `count_files_needing_reconciliation` therefore stays > 0 forever and `start_write_tags_background`'s task loop re-claims the same file every second and never reaches a terminal state. The pipeline `tag_write` axis stays `writing` and the completion callback (Navidrome rescan) never fires. The two `on_complete` consumers are incoherent — the pipeline callback raises `RuntimeError` (recorded as a BTS `error`) while the API callback would fire an unconditional rescan. `file_modified_externally` is a second non-terminating path. Transient filesystem/network failures were indistinguishable from persistent ones, and retryability was inferred from human-readable error strings. The archived `DD-background-task-standardization.md` stance ("No retry/backoff … Tasks run once … Retry is the caller's decision") targeted the abandoned task-level poll/exponential-backoff design and did not address a bounded in-task retry of an idempotent per-file boundary operation. This decision depends on ADR-050: retryability is expressed over that contract's structured filesystem facts, never over error strings.

## Decision

1. A tag-write run applies a bounded per-file retry budget: at most N = 3 total attempts per file per run, with a fixed, short, bounded in-run delay between attempts (cancel-responsive). Retryability is decided by ONE non-retryable predicate over the structured `WriteResult.fs_fact`/`WriteResult.outcome` defined by ADR-050 — a non-retryable condition is `outcome ∈ {modified_externally, probe_unsupported, song_record_missing, library_unresolved}`, a corroborated `fs_fact.presence == "absent"`, or `fs_fact.kind ∈ {invalid_path, wrong_resource_type}`; every other outcome/fact (transient/storage/permission/unconfirmed kinds, `audio_sanity_failed`, `probe_failed_transient`, `write_failed`, `None`/unknown) receives the bounded allowance. Attempt counters are run-local and keyed by `SongIdentity`. There is NO persistence, durable failure ledger, persistent cooldown, scheduler, exponential backoff, or generalized BTS retry machinery. A new independently triggered run receives a fresh attempt budget. Retryability remains `TaggingService` policy.

2. The run terminates when `remaining == 0` (`outcome=complete`), when no eligible candidate remains while `remaining > 0` (`outcome=partial` — every locator either succeeded or entered the run-scoped exclusion set), or on `stop_event` (`cancelled`). Exhaustion of the retry budget enters the exclusion set and the run continues; it never re-enters the same run.

3. A partial run is published as BTS `complete` carrying a failure-bearing `WriteTagsResult(outcome=partial)`; the BTS status taxonomy is unchanged.

4. Both `on_complete` consumers have an explicit partial-success policy: the pipeline `tag_write` axis returns to `not_written` (no raise), and the Navidrome rescan fires only on full drain. Full-drain-only rescan is a product policy of this decision, explicitly not derived from ADR-044.

5. Failed files are not marked written (`set_file_written` only on success) and remain resumable through the existing `POST /{library_name}/write-tag` with a fresh budget.

6. Supersession/scoping of the archived stance: the archived `DD-background-task-standardization.md` statements ("Retry/backoff logic: Explicitly rejected … Tasks run once; retry is the caller's decision." and "No retry/backoff … Tasks run once. If they fail, status is \"error\". Retry is the caller's decision.") are scoped — they continue to prohibit (a) automatic task-level retry/re-dispatch and (b) persistent/scheduled backoff, but they do not prohibit a bounded, in-run, non-persistent retry budget for an idempotent per-file boundary operation inside a single task. To the extent the archived wording could be read as forbidding all retries, this decision supersedes that reading. The archived item is a design document, not an ADR, so no ADR is superseded. The filesystem taxonomy itself is NOT restated here; see ADR-050.

## Consequences

Positive: tag-write loops become provably finite (each locator consumes at most N attempts before succeeding or being excluded); partial runs stop stranding the pipeline axis at `writing`; the completion callback fires only when a rescan is actually correct; persistent per-file failures stay visibly pending (live `pending_count`) for operator retry; transient failures get a bounded automatic recovery without durable machinery.

Negative / accepted: a partial run still reports BTS `complete` (with a failure-bearing result), so consumers must read the outcome rather than the BTS status alone; the per-file failure reason is not durable (a durable ledger / quarantine was explicitly rejected as scope inflation and remains a deferred enhancement); `permission_denied` remains retryable-bounded, so a permanently unreadable file consumes its budget each run.

No new persistence, endpoint, BTS status, or pipeline axis pole is introduced; `ManagedTask` and the BTS taxonomy are unchanged.

## References

Design: `artifacts/designs/pending/DD-tag-write-reconciliation-terminal-failure.md` (v0.8). Depends on ADR-050. Process: `artifacts/designs/process/ARCHITECTURE-tag-write-reconciliation-terminal-failure.md`, `ADVERSARIAL-tag-write-reconciliation-terminal-failure.md` (+SUMMARY), `ESTIMATE-tag-write-reconciliation-terminal-failure.md`. Related: ADR-003 (pure boolean state graph), ADR-008 (partial success legitimate, idempotent retry), ADR-013 (write policy on TaggingService), ADR-021 (file length), ADR-044 (Nomarr never persists Navidrome data locally), ADR-046. Archived stance being scoped: `artifacts/designs/archive/DD-background-task-standardization.md` (Out of Scope line 41; Constraints line 366). Source finding: GitHub issue #162.
