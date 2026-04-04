# Task: History Cleanup — E: Worker Architecture Era

## Problem Statement
From the discovery worker foundation (e61b693) through the forward-only migration system (57a84c2), approximately 30 commits cover: lazy ML cache warmup, pipe health telemetry, worker restart/backoff policy, crash handling, heartbeat reliability, logging standardization, and the persistence migration system. Many are small follow-up fixes to the worker architecture.

Target: collapse ~30 commits into ~6:
1. `feat: discovery-based workers with pipe health telemetry and lazy ML warmup`
2. `feat: worker restart/backoff policy and crash recovery`
3. `feat: standardize logging with auto identity/role tags`
4. `fix: worker heartbeat reliability, skip handling, and termination`
5. `feat: forward-only database migration system`
6. `chore(code-intel): MCP tooling — naming conventions and edit tools`

**Prerequisite:** TASK-history-cleanup-D-filewatcher-scan-era

## Phases

### Phase 1: Enumerate and Group
- [ ] Run `git log --oneline <D-end-sha>..57a84c2` to list all commits in this era
- [ ] Identify code-intel-only commits in this range (`git log --oneline <D-end>..57a84c2 -- code-intel/`) — group into the single code-intel commit
- [ ] Identify worker reliability fixups that belong in the worker architecture commits vs. the restart policy commit
- [ ] Mark all `fix(workers):`, `fix(persistence):` commits from this era as squash targets into their parent feature
- [ ] Draft rebase todo

### Phase 2: Execute Rebase
- [ ] Run `git rebase -i <D-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some around worker state dict and logging setup
- [ ] Verify result: ~6 commits in this era

### Phase 3: Validate
- [ ] Run `git diff HEAD <original-57a84c2> -- nomarr/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan F

## Completion Criteria
- Era contains ~6 commits
- Worker architecture feature commits absorb all their fixup commits
- Tree diff against original 57a84c2 is empty
- Tests pass

## References
- Previous: TASK-history-cleanup-D-filewatcher-scan-era
- Next: TASK-history-cleanup-F-ml-vectors-era
