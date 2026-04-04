# Task: History Cleanup — G: Docker/CUDA and Performance Era

## Problem Statement
From the CUDA 12.5 bump (dca607a) through the performance plateau (~77c499f), approximately 40 commits cover two interleaved stories: (1) the long Docker/CUDA grind — 9+ fix commits chasing the `feat: bump to CUDA 12.5 + TF 2.18.0` upgrade, and (2) the performance burst — timing instrumentation scaffolding, batch DB writes, parallel ML pipeline, persistent audio loader, and patch overlap reduction. The timing instrumentation commits are pure scaffolding that was never meant to be permanent history.

Target: collapse ~40 commits into ~6:
1. `feat: CUDA 12.5 + TF 2.18.0 + Ubuntu 24.04 Docker upgrade`
2. `fix: cuDNN 9.3, XLA ptxas, libdevice, and CUDA image build fixes`
3. `perf: batch DB writes — 90 roundtrips to 4 per file`
4. `perf: parallel ML pipeline + persistent audio loader (2.5x throughput)`
5. `perf: patch overlap reduction and recalibration pipeline bulk queries`
6. `chore(deps): bump backend and frontend dependencies`

**Prerequisite:** TASK-history-cleanup-F-ml-vectors-era

## Phases

### Phase 1: Enumerate and Group
- [ ] Run `git log --oneline <F-end-sha>..77c499f` to list all commits in this era
- [ ] Identify all timing instrumentation commits: `perf: Add timing instrumentation`, `perf: Add ultra-verbose per-operation timing`, `perf: Show DB write time in milliseconds`, `perf: Add timing instrumentation to measure DB write overhead` — all 4+ are scaffolding; squash into the perf commit they enabled or drop if superseded
- [ ] Identify all Docker/CUDA fix commits (9 of them) and group into the 2 Docker target commits above
- [ ] Identify all dependabot-related merge commits in this era and group into the deps commit
- [ ] Draft rebase todo

### Phase 2: Execute Rebase
- [ ] Run `git rebase -i <F-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some in dockerfile and ML pipeline; Docker fixes are self-contained so conflicts should be minimal
- [ ] Drop the timing instrumentation commits (confirmed: their purpose was served by the perf commits they preceded)
- [ ] Verify result: ~6 commits in this era

### Phase 3: Validate
- [ ] Run `git diff HEAD <original-77c499f> -- nomarr/ dockerfile dockerfile.base` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan H

## Completion Criteria
- Era contains ~6 commits
- Docker upgrade is a single self-contained commit (feat + all fixes together)
- All timing instrumentation scaffolding is gone from history
- Tree diff against original 77c499f is empty
- Tests pass

## References
- Previous: TASK-history-cleanup-F-ml-vectors-era
- Next: TASK-history-cleanup-H-calibration-era
