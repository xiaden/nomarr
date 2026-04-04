# Task: History Cleanup — J: Vector Systems and Migration Hardening Era

## Problem Statement
From the insights UI refactor (aa6d0d3) through the vector normalization + migration hardening commit (2e45246), approximately 15 commits cover: the docs and utility script updates, the insights/calibration UI polish, and then the two substantial feature sets: APPROX_NEAR_COSINE score normalization (dual-field vector_n approach) and the migration system hardening (4 defects fixed). These are already fairly clean commits — recent work from this session.

Target: collapse ~15 commits into ~5:
1. `docs: update calibration troubleshooting, add utility scripts`
2. `feat(frontend): refactor insights UI, move accordions to shared`
3. `fix: Always clear all 3 mood tiers on DB write`
4. `chore: replace Essentia AutoTag references with Nomarr`
5. `fix: normalize cold vector embeddings and harden migration system` (already clean — keep as-is)

**Prerequisite:** TASK-history-cleanup-I-frontend-era

## Phases

### Phase 1: Enumerate and Group
- [ ] Run `git log --oneline <I-end-sha>..2e45246` to list all commits in this era
- [ ] Identify any small fixup commits between aa6d0d3 and the vector normalization work — these should be grouped with either the preceding feature or the mood tier fix
- [ ] Confirm the vector normalization + migration hardening commit (2e45246) stays intact as-is — it is already a clean, well-scoped commit
- [ ] Draft rebase todo

### Phase 2: Execute Rebase
- [ ] Run `git rebase -i <I-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Conflicts expected: minimal — this is recent, clean history
- [ ] Verify result: ~5 commits in this era

### Phase 3: Validate
- [ ] Run `git diff HEAD 2e45246 -- nomarr/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan K

## Completion Criteria
- Era contains ~5 commits
- Vector normalization commit preserved intact
- Tree diff against original 2e45246 is empty
- Tests pass

## References
- Previous: TASK-history-cleanup-I-frontend-era
- Next: TASK-history-cleanup-K-navidrome-recent-era
