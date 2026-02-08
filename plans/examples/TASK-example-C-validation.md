# Task: Example - Validation

## Problem Statement

Validation phase for the comprehensive example refactor. Verify implementation correctness through automated and manual testing.

**Parent plan:** `TASK-example-comprehensive.md` (orchestrator)

**Prerequisite:** `TASK-example-B-implementation.md` must be complete

## Phases

### Phase 1: Automated Verification

- [ ] All lint checks pass with zero errors
- [ ] All existing tests pass (no regressions)
- [ ] New unit tests cover added functionality (>80% coverage on new code)

### Phase 2: Manual Verification

- [ ] Primary use case: session auth flow end-to-end
- [ ] Primary use case: API key auth flow end-to-end
- [ ] Edge case: legacy token bridge for external integrations
- [ ] Edge case: token expiration and refresh

**Blocked:** Cannot complete manual verification until test environment is provisioned (external dependency - ops team ticket #456)

## Completion Criteria

- Zero lint errors
- Zero test failures
- All manual verification scenarios documented with pass/fail
- No suppression comments added (`# type: ignore`, `# noqa`)

## References

- Parent: `plans/examples/TASK-example-comprehensive.md`
- Prerequisite: `plans/examples/TASK-example-B-implementation.md`
- Siblings: A-discovery, D-cleanup
