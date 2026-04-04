# Task: History Cleanup — I: Frontend Buildout Era

## Problem Statement
From calibration complete (f9d7fd2) through the insights UI refactor (aa6d0d3), approximately 40 commits cover the frontend-heavy era: replacing NavTabs with a collapsible sidebar, the Navidrome/smart playlist rules engine, the dashboard improvements, frontend dependency bumps, and the insights/analytics page buildout. Many `chore: rebuild frontend` and `build: rebuild frontend` commits are pure noise — they exist because source was committed separately from its build artifact.

Target: collapse ~40 commits into ~8:
1. `refactor(frontend): collapsible sidebar, merge Admin into Config`
2. `feat(navidrome): visual playlist rules engine with nested rule groups`
3. `feat(frontend): dashboard improvements — recent activity, charts`
4. `feat(frontend): analytics pages — collection overview, mood analysis, insights`
5. `feat(frontend): accordion components with localStorage persistence`
6. `fix(frontend): calibration UI integration fixes and notification system`
7. `chore(deps): bump backend and frontend dependencies`
8. `chore(code-intel): plan tooling and MCP audience-targeted responses`

**Prerequisite:** TASK-history-cleanup-H-calibration-era

## Phases

### Phase 1: Enumerate and Group
- [ ] Run `git log --oneline <H-end-sha>..aa6d0d3` to list all commits in this era
- [ ] Identify all standalone `chore: rebuild frontend` / `build: rebuild frontend` commits — every one of these gets squashed into the feature commit it was built for
- [ ] Identify all dependabot merge commits in this range and group into the single deps commit
- [ ] Identify code-intel-only commits in this range and group into the code-intel commit
- [ ] Identify the WIP graph viewer commits — confirm work was abandoned and mark as drop
- [ ] Draft rebase todo

### Phase 2: Execute Rebase
- [ ] Run `git rebase -i <H-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect frontend src conflicts if build artifacts were committed out of order with source
- [ ] Drop the WIP graph viewer commits (confirmed abandoned)
- [ ] Verify each remaining commit has both source and build artifact together
- [ ] Verify result: ~8 commits in this era

### Phase 3: Validate
- [ ] Run `git diff HEAD <original-aa6d0d3> -- nomarr/ frontend/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan J

## Completion Criteria
- Era contains ~8 commits
- No standalone `rebuild frontend` commits remain
- WIP/abandoned graph viewer work is gone from history
- All dependabot noise collapsed into single deps commit
- Tree diff against original aa6d0d3 is empty
- Tests pass

## References
- Previous: TASK-history-cleanup-H-calibration-era
- Next: TASK-history-cleanup-J-vector-migration-era
