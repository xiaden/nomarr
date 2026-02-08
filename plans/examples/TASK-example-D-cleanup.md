# Task: Example - Cleanup

## Problem Statement

Cleanup phase for the comprehensive example refactor. Remove deprecated code and update documentation.

**Parent plan:** `TASK-example-comprehensive.md` (orchestrator)

**Prerequisite:** `TASK-example-C-validation.md` must be complete (don't delete code until it's verified working)

## Phases

### Phase 1: Code Cleanup

- [ ] Remove deprecated legacy_token code paths
- [ ] Remove temporary adapter shims (if external integrations have migrated)
- [ ] Clean up feature flags used during rollout

**Warning:** Verify external integration migration status before removing adapter. Check with integrations team.

### Phase 2: Documentation

- [ ] Update API documentation to reflect new auth patterns
- [ ] Create migration guide for any remaining legacy users
- [ ] Update architecture diagrams

## Completion Criteria

- No dead code remaining
- Documentation reflects actual behavior
- Migration guide published (if breaking changes affect users)

## References

- Parent: `plans/examples/TASK-example-comprehensive.md`
- Prerequisite: `plans/examples/TASK-example-C-validation.md`
- Siblings: A-discovery, B-implementation
