# Task: History Cleanup — H: Calibration System Era

## Problem Statement
From the performance plateau (~77c499f) through the calibration complete commit (f9d7fd2), approximately 35 commits cover the full calibration system: non-blocking apply with background threading, the histogram-based calibration refactor, convergence tracking, progressive calibration, the calibration clear feature, and the frontend calibration UI (apply progress polling, charts). Several commits fix things that the calibration implementation broke (histogram AQL bugs, chart regressions, progress bar, tier reconstruction).

Target: collapse ~35 commits into ~7:
1. `feat: non-blocking calibration apply with background threading`
2. `feat: histogram-based calibration with convergence tracking`
3. `feat: progressive calibration with educational histogram examples`
4. `fix: calibration AQL fixes — bind vars, scope, label mismatch, histogram limit`
5. `feat: calibration apply progress UI with polling`
6. `feat: calibration clear feature`
7. `fix: chart tooltip alignment, overflow, and convergence chart isolation`

**Prerequisite:** TASK-history-cleanup-G-docker-cuda-performance-era

## Phases

### Phase 1: Enumerate and Group
- [ ] Run `git log --oneline <G-end-sha>..f9d7fd2` to list all commits in this era
- [ ] Identify the AQL bug chain: `fix: sanitize calibration _key`, `fix: use bind vars after COLLECT`, `fix: file_id-based sync`, `fix: calibration head_name→labels mismatch`, `fix: move LIMIT after FILTERs` — these all belong in the AQL fixes commit
- [ ] Identify chart regression fixups and group with the convergence chart feature commit
- [ ] Identify any performance commits in this range (`perf: eliminate ~150k redundant DB queries in calibration apply`) — keep as distinct perf commit
- [ ] Draft rebase todo

### Phase 2: Execute Rebase
- [ ] Run `git rebase -i <G-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some in calibration workflow and AQL files
- [ ] Verify result: ~7 commits in this era

### Phase 3: Validate
- [ ] Run `git diff HEAD <original-f9d7fd2> -- nomarr/ frontend/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan I

## Completion Criteria
- Era contains ~7 commits
- All AQL fix commits absorbed into the calibration features they fix
- Chart fixup commits absorbed into the chart feature commits
- Tree diff against original f9d7fd2 is empty
- Tests pass

## References
- Previous: TASK-history-cleanup-G-docker-cuda-performance-era
- Next: TASK-history-cleanup-I-frontend-era
