# Task: History Cleanup — A: Setup and Safety Net

## Problem Statement

The nomarr git history has ~739 commits with significant noise: fix-chasing, debug scaffolding, repeated frontend rebuild commits, a long Docker/CUDA grind, and 20+ dependabot merge commits. The goal is to collapse this to ~50–70 semantically clean commits where every SHA in the final history represents a working product state.

This is plan A of 12. It establishes the safety net, documents all era boundary SHAs, and confirms the baseline before any rebase begins. No history is modified here.

## Phases

### Phase 1: Safety Net

- [ ] Tag current HEAD as `pre-cleanup-backup` with `git tag pre-cleanup-backup HEAD` and push the tag to origin
- [ ] Create working branch `history-cleanup` from current HEAD
- [ ] Record current commit count with `git rev-list --count HEAD` and note it in a scratch file (not committed)
- [ ] Confirm pytest passes: `pytest tests/ -q` — establish baseline before touching anything

### Phase 2: Map Era Boundaries

- [ ] Run `git log --oneline --reverse` and identify the SHA for each of these 13 boundary commits: initial commit, v0.1 (d5d0d93), ArangoDB migration complete (b9d9a94), FileWatcher phase 4 (ede68ec), discovery worker architecture (e61b693), migration system + vector pooling (57a84c2 / faccba7), CUDA bump start (dca607a), parallel ML (bb48b87), performance plateau (~77c499f), calibration complete (f9d7fd2), insights UI refactor (aa6d0d3), vector normalization (2e45246), HEAD
- [ ] For each era, run `git log --oneline <start>..<end> -- code-intel/` to count code-intel-only commits — note which eras have significant code-intel activity to handle carefully
- [ ] Identify all WIP commits (`git log --oneline --grep='WIP'`) and decide: squash into landing commit (if work landed) or drop (if abandoned)
- [ ] Identify all debug-scaffolding commits (`git log --oneline --grep='debug:'`) and mark them all as squash targets

### Phase 3: Rebase Strategy Decisions

- [ ] Confirm the SQLite→ArangoDB mega-squash strategy: everything from 4a57632 through b9d9a94 (exclusive) collapses to ~6 commits in plan B — verify this range with `git log --oneline 4a57632..b9d9a94`
- [ ] Document the code-intel handling rule: code-intel-only commits in each era get squashed into 1–2 `chore(code-intel): ...` commits per era rather than a separate pass
- [ ] Confirm the dependabot strategy: all `Merge pull request` + individual bump commits get squashed into 1 `chore(deps): bump dependencies` per era
- [ ] Verify `git rebase -i` is available and working with a dry-run test on a throwaway branch

## Completion Criteria

- `pre-cleanup-backup` tag exists on origin
- `history-cleanup` branch exists locally
- All 13 era boundary SHAs are documented
- Baseline test suite passes
- No history has been modified

## References

- Plans B through L define the actual rebase work per era
