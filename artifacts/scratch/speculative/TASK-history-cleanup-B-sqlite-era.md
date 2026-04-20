# Task: History Cleanup — B: SQLite Era (Initial → ArangoDB Migration)

## Problem Statement

The oldest ~80 commits (4a57632 through b9d9a94 exclusive) represent the SQLite era of nomarr. This includes: the initial audio tagging system, the early calibration phase commits (Phase 3A–3E), the v0.1 tagging system, and the full SQLite→ArangoDB migration which was a near-total rewrite. This history predates good commit hygiene.

Target: collapse ~80 commits into ~6:

1. `feat: initial Nomarr audio tagging system` (4a57632 → d5d0d93)
2. `feat: recalibration system and library auto-tagging`
3. `feat: calibration infrastructure and worker system`
4. `refactor: tag normalization and queue architecture`
5. `chore: CI, Docker, and dependency setup`
6. `feat: complete ArangoDB migration` (the disgusting mega-squash — b9d9a94 and all SQLite→ArangoDB transition commits)

**Prerequisite:** TASK-history-cleanup-A-setup

## Phases

### Phase 1: Enumerate and Group

- [ ] Run `git log --oneline 4a57632..b9d9a94` and list all commits in this era
- [ ] Group commits into the 6 target categories above — assign each SHA to a group
- [ ] Identify any commits that touch both SQLite schema AND feature code (these anchor the group boundaries)
- [ ] Draft the full rebase todo file for this range (pick/squash/drop decisions for all ~80 commits)

### Phase 2: Execute Rebase

- [ ] On the `history-cleanup` branch, run `git rebase -i 4a57632~1` with the prepared todo
- [ ] Resolve any conflicts — in this era, expect conflicts around the tag normalization refactors and the queue architecture changes
- [ ] Write commit messages for each of the 6 squashed commits — messages should describe the final state, not the journey
- [ ] Verify the result: `git log --oneline 4a57632..b9d9a94-equivalent` should show exactly 6 commits

### Phase 3: Validate

- [ ] Run `git diff HEAD b9d9a94 -- nomarr/` to confirm the diff is empty (same final state despite compressed history)
- [ ] Run `pytest tests/ -q` on the post-rebase state
- [ ] Note the new boundary SHA (equivalent of old b9d9a94) for use in plan C

## Completion Criteria

- Era contains exactly ~6 commits
- Every remaining commit represents a working product state
- Final tree diff against original b9d9a94 is empty
- Tests pass

## References

- Previous: TASK-history-cleanup-A-setup
- Next: TASK-history-cleanup-C-library-entity-era
