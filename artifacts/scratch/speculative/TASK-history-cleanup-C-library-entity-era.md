# Task: History Cleanup — C: Library/Entity Era

## Problem Statement

After the ArangoDB migration (b9d9a94), the codebase spent ~40 commits building out the library/entity/scan system: multi-library management, the entity graph (metadata cache), scan API refactors, ArangoDB credential/DNS fixes, and extensive documentation updates for the SQLite→ArangoDB transition. Many of these commits are small fixups that should be absorbed into the feature they were fixing.

Target: collapse ~40 commits into ~7:

1. `feat: multi-library management with ArangoDB`
2. `feat: entity graph and metadata cache`
3. `feat: hierarchical library browser with tag navigation`
4. `refactor: library scan API and FileWatcher groundwork`
5. `fix: ArangoDB startup, healthcheck, and credential flow`
6. `chore(deps): bump dependencies`
7. `docs: update all documentation for ArangoDB`

**Prerequisite:** TASK-history-cleanup-B-sqlite-era

## Phases

### Phase 1: Enumerate and Group

- [ ] Run `git log --oneline <B-end-sha>..ede68ec` to list all commits in this era
- [ ] Identify the ArangoDB infra fixup cluster: `fix(startup)`, `fix(docker)`, `fix(startup)` commits that exist only because the migration left things broken — group these into the ArangoDB fixup commit
- [ ] Identify doc-only commits (all the `docs: update all docs from SQLite to ArangoDB` series) — these collapse into 1 docs commit
- [ ] Draft rebase todo for this range

### Phase 2: Execute Rebase

- [ ] Run `git rebase -i <B-end-sha>` with prepared todo on `history-cleanup` branch
- [ ] Resolve conflicts — expect some in the library DTO and scan API areas
- [ ] Write clean commit messages describing each feature's final delivered state
- [ ] Verify result: `git log --oneline <B-end>..` shows ~7 commits

### Phase 3: Validate

- [ ] Run `git diff HEAD <original-ede68ec> -- nomarr/` to confirm tree is identical
- [ ] Run `pytest tests/ -q`
- [ ] Note new boundary SHA for plan D

## Completion Criteria

- Era contains ~7 commits
- No commit in the era fixes something broken by the previous commit in the era
- Tree diff against original ede68ec is empty
- Tests pass

## References

- Previous: TASK-history-cleanup-B-sqlite-era
- Next: TASK-history-cleanup-D-filewatcher-scan-era
