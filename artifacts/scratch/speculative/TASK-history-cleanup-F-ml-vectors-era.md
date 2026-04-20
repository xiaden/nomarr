# Task: History Cleanup — F: ML Systems and Vectors Era

## Problem Statement

From the migration system (57a84c2) through the CUDA bump (dca607a, exclusive), approximately 25 commits cover: vector pooling and segment statistics, device-aware predictor cache, the crash-safe audio loader (os.fork isolation), mood label extraction and tagging refactors, and various ML pipeline improvements. These were relatively clean feature commits but with a few fixup chains.

Target: collapse ~25 commits into ~6:

1. `feat: Add vector pooling and segment statistics to ML pipeline`
2. `feat: device-aware predictor cache with GPU/CPU tracking`
3. `feat: crash-safe audio loading via os.fork + pipe isolation`
4. `refactor: mood label extraction, tier system, and tag reconstruction`
5. `fix: ML pipeline fixes — TF session, TF GPU init, XLA, libdevice`
6. `chore(code-intel): MCP tooling updates`

**Prerequisite:** TASK-history-cleanup-E-worker-architecture-era

## Phases

### Phase 1: Enumerate and Group

- [ ] Run `git log --oneline <E-end-sha>..dca607a~1` to list all commits in this era
- [ ] Identify the TF/XLA/GPU init fix chain (`fix: include libdevice`, `fix: point XLA_FLAGS`, `fix: include ptxas`) — these belong together as one ML infrastructure fix commit
- [ ] Identify the mood/tagging refactor cluster — several commits around `extract mood labels`, `simplify aggregation`, `add tag reconstruction` should collapse
- [ ] Mark `debug: add detailed logging to tag generation pipeline` as squash into the mood refactor (debug scaffolding)
- [ ] Draft rebase todo

### Phase 2: Execute Rebase

- [ ] Run `git rebase -i <E-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some in ML component and tagging workflow areas
- [ ] Verify result: ~6 commits in this era

### Phase 3: Validate

- [ ] Run `git diff HEAD <original-dca607a~1> -- nomarr/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan G

## Completion Criteria

- Era contains ~6 commits
- All ML infrastructure fixups absorbed into feature commits
- Tree diff against original era end is empty
- Tests pass

## References

- Previous: TASK-history-cleanup-E-worker-architecture-era
- Next: TASK-history-cleanup-G-docker-cuda-performance-era
