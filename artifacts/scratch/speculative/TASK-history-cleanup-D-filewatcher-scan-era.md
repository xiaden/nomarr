# Task: History Cleanup — D: FileWatcher and Scan Era

## Problem Statement

From the FileWatcher implementation (ede68ec) through the discovery worker architecture (e61b693), approximately 30 commits cover: the scan API deep clean, incremental scan refactor (Phases 1–4), the FileWatcherService itself with its polling mode, and the entity cleanup + discovery worker system. These were implemented as phase-by-phase plan commits with several fixup commits in between.

Target: collapse ~30 commits into ~5:

1. `refactor: scan API deep clean — remove all unused parameters`
2. `feat: incremental scan pipeline with LibraryService scan_targets()`
3. `feat: FileWatcherService with network-mount-safe polling mode`
4. `feat: entity cleanup system and discovery worker architecture`
5. `fix: FileWatcher integration, path compatibility, and startup fixes`

**Prerequisite:** TASK-history-cleanup-C-library-entity-era

## Phases

### Phase 1: Enumerate and Group

- [ ] Run `git log --oneline <C-end-sha>..e61b693` to list all commits in this era
- [ ] Identify the Phase 1–4 scan refactor commits and group all of them plus their fixups into the incremental scan commit
- [ ] Identify FileWatcher Phase 4 + docs + integration fixes — these all belong in the FileWatcher feature commit
- [ ] Mark `docs: complete Phase 6 - comprehensive FileWatcherService documentation` as squash into the FileWatcher commit (docs belong with the feature)
- [ ] Draft rebase todo

### Phase 2: Execute Rebase

- [ ] Run `git rebase -i <C-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some around scan_library_direct_wf and worker state
- [ ] Verify result: ~5 commits in this era

### Phase 3: Validate

- [ ] Run `git diff HEAD <original-e61b693> -- nomarr/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan E

## Completion Criteria

- Era contains ~5 commits
- FileWatcher feature is fully self-contained in its commit (no followup fix commits)
- Tree diff against original e61b693 is empty
- Tests pass

## References

- Previous: TASK-history-cleanup-C-library-entity-era
- Next: TASK-history-cleanup-E-worker-architecture-era
