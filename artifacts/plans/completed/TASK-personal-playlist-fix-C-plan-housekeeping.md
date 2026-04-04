# Task: Personal Playlist Fix C — Plan Housekeeping

## Problem Statement

Plans A through G for the personal playlist feature are fully implemented (code exists, audits passed, 0 lint errors), but plans C, E, F, and G were never marked complete in their plan files due to a subagent bookkeeping failure. All 7 plan files need their steps marked `[x]` and then moved to `plans/completed/`.

**Prerequisite:** None (independent of Fix A and B)

## Phases

### Phase 1: Mark and Archive
- [x] Mark all steps `[x]` in `plans/TASK-personal-playlist-C-sync-rewrite.md` (7 steps across 2 phases).
    **Notes:** Verified: All steps marked [x] in plans/completed/TASK-personal-playlist-C-sync-rewrite.md.
- [x] Mark all steps `[x]` in `plans/TASK-personal-playlist-E-playlist-generation.md` (11 steps across 2 phases).
    **Notes:** Verified: All steps marked [x] in plans/completed/TASK-personal-playlist-E-playlist-generation.md.
- [x] Mark all steps `[x]` in `plans/TASK-personal-playlist-F-config-frontend.md` (6 steps across 2 phases).
    **Notes:** Verified: All steps marked [x] in plans/completed/TASK-personal-playlist-F-config-frontend.md.
- [x] Mark all steps `[x]` in `plans/TASK-personal-playlist-G-plugin-scrobbler.md` (8 steps across 2 phases).
    **Notes:** Verified: All steps marked [x] in plans/completed/TASK-personal-playlist-G-plugin-scrobbler.md.
- [x] Move all 7 plan files (A through G) from `plans/` to `plans/completed/`. Plans A, B, D are already marked complete but not yet archived.
    **Notes:** Verified: All 7 plan files (A through G) are in plans/completed/. Zero TASK-personal-playlist-[A-G] files in plans/ root.

## Completion Criteria
- All steps in all 7 plan files show `[x]`
- All 7 files live under `plans/completed/`
- No `TASK-personal-playlist-[A-G]` files remain in `plans/` root

## References
- Plans A, B, D: Already marked `[x]` but not moved
- Plans C, E, F, G: Steps still `[ ]` despite code being implemented
- Audit results: All 7 plans passed ALL CHECKS in prior session
