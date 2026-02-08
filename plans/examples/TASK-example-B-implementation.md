# Task: Example - Implementation

## Problem Statement

Implementation phase for the comprehensive example refactor. Build the new abstractions and migrate callers.

**Parent plan:** `TASK-example-comprehensive.md` (orchestrator)

**Prerequisite:** `TASK-example-A-discovery.md` must be complete (stakeholder sign-off required)

## Phases

### Phase 1: Core Abstractions

- [ ] Create base abstraction interface
- [ ] Implement session-based auth variant
- [ ] Implement API-key auth variant

### Phase 2: Migration

- [ ] Add configuration for edge cases (legacy token bridge)
- [ ] Update all internal callers to use new abstraction
- [ ] Create adapter for external integrations (non-breaking migration path)

**Notes:** Implementation order matters - base abstraction must be complete before variants. Migration can't start until all variants exist.

## Completion Criteria

- Base abstraction and all variants implemented
- All internal callers migrated
- External integration adapter in place
- Code compiles with no type errors

## References

- Parent: `plans/examples/TASK-example-comprehensive.md`
- Prerequisite: `plans/examples/TASK-example-A-discovery.md`
- Siblings: C-validation, D-cleanup
