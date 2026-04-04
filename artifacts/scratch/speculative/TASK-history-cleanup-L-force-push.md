# Task: History Cleanup — L: Final Validation and Force Push

## Problem Statement
Plans A through K have rewritten the full git history of nomarr on the `history-cleanup` branch. The final step is to validate the complete cleaned history end-to-end, confirm the total commit count is in the target range (~50–70 commits), verify the tree at HEAD is identical to the pre-cleanup state, and force push to replace origin/main.

**This is a destructive, irreversible operation on the remote.** The `pre-cleanup-backup` tag must exist on origin before proceeding.

**Prerequisite:** TASK-history-cleanup-K-navidrome-recent-era

## Phases

### Phase 1: End-to-End Validation
- [ ] Confirm `pre-cleanup-backup` tag exists on origin with `git ls-remote --tags origin pre-cleanup-backup`
- [ ] Run `git rev-list --count HEAD` — confirm total is in the 50–70 range
- [ ] Run `git diff HEAD pre-cleanup-backup -- nomarr/ frontend/ code-intel/ docs/` — must be empty (identical trees)
- [ ] Run `pytest tests/ -q` on the cleanup branch HEAD — must pass
- [ ] Run `mcp_nomarr_dev_lint_project_backend()` — zero errors
- [ ] Spot-check 5 intermediate SHAs: checkout each, confirm the product builds (lint passes)

### Phase 2: Force Push
- [ ] Verify no other contributors have pushed to main since the cleanup branch was created (check origin/main SHA vs expected)
- [ ] Run `git push origin history-cleanup:main --force-with-lease` — `--force-with-lease` adds a safety check that origin/main hasn't moved unexpectedly
- [ ] Verify origin/main now points to the new cleanup HEAD
- [ ] Push the `pre-cleanup-backup` tag if not already on origin: `git push origin pre-cleanup-backup`

### Phase 3: Cleanup and Documentation
- [ ] Delete the local `history-cleanup` branch: `git branch -d history-cleanup`
- [ ] Run `git log --oneline | Measure-Object -Line` to confirm final commit count
- [ ] Verify GitHub web UI shows the clean history

## Completion Criteria
- `git diff HEAD pre-cleanup-backup` is empty
- Total commit count is 50–70
- `pre-cleanup-backup` tag exists on origin as the escape hatch
- origin/main points to the cleaned history
- Tests and lint pass on final HEAD
- No working tree changes lost

## References
- Previous: TASK-history-cleanup-K-navidrome-recent-era
- Escape hatch: `git push origin pre-cleanup-backup:main --force` to restore if needed
