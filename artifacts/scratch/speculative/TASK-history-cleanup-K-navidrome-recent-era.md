# Task: History Cleanup — K: Navidrome Integration and Recent Era

## Problem Statement
From the vector normalization commit (2e45246) through HEAD, approximately 8 commits cover: the Navidrome Subsonic client backend integration, the rebuild-index workflow, the frontend browse and vector search UI changes, and the workspace config. These were committed in scoped, clean commits — but the code-intel plan_md fix from another agent (fbbc186) landed out-of-order in the middle. The goal is to verify these commits are clean and reorder if needed.

Target: ~6–7 commits (already clean, minimal squashing):
1. `fix(code-intel): fix byte-offset truncation in plan_md parser` (fbbc186)
2. `feat(navidrome): backend Subsonic client integration`
3. `feat(vectors): rebuild-index workflow and expanded vector API`
4. `feat(frontend/browse): Navidrome browse and search UI`
5. `feat(frontend/vectors): vector search UI enhancements`
6. `build(frontend): update compiled public_html assets`
7. `chore: update workspace config`

**Prerequisite:** TASK-history-cleanup-J-vector-migration-era

## Phases

### Phase 1: Review and Order
- [ ] Run `git log --oneline <J-end-sha>..HEAD` to list all commits in this era
- [ ] Confirm the code-intel plan_md fix (fbbc186) is self-contained and does not need to be reordered — it can remain where it landed since it only touches code-intel/
- [ ] Confirm the workspace config commit can be squashed into an adjacent commit or kept as-is
- [ ] Decide if `build(frontend): update compiled public_html assets` should be merged into the frontend feature commit that preceded it or kept separate for clarity

### Phase 2: Execute Light Rebase
- [ ] Run `git rebase -i <J-end-sha>` with the prepared todo on `history-cleanup` branch
- [ ] Conflicts expected: none — this is the freshest history
- [ ] Squash workspace config into the most logically adjacent commit
- [ ] Verify result: 6–7 commits

### Phase 3: Validate
- [ ] Run `pytest tests/ -q` — must pass
- [ ] Run `mcp_nomarr_dev_lint_project_backend()` — must be zero errors
- [ ] Run `mcp_nomarr_dev_lint_project_frontend()` — must be zero errors
- [ ] Note final HEAD SHA — this becomes the new main after plan L

## Completion Criteria
- Era contains 6–7 commits
- All commits are topologically correct (related frontend source + assets in same commit)
- All linting and tests pass on final HEAD

## References
- Previous: TASK-history-cleanup-J-vector-migration-era
- Next: TASK-history-cleanup-L-force-push
