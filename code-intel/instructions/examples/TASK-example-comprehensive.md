# Task: Comprehensive Example Plan

## Problem Statement

This is a reference plan demonstrating all formatting elements recognized by the plan parser. Use this as a template when creating new task plans.

**Context for fresh models:** Plans are structured markdown files that enable cross-session task continuity. A model starting fresh should be able to read this plan and understand exactly what's been done, what's next, and any blockers or warnings accumulated along the way.

Key elements:
- **Phases** group steps by semantic outcome (not by file or method)
- **Steps** are atomic, verifiable actions with auto-generated IDs (P1-S1, P1-S2, etc.)
- **Annotations** capture decisions, warnings, and blockers at phase or step level
- **Completion Criteria** define measurable success conditions

## Phases

### Phase 1: Discovery

- [x] Identify all components affected by the change
    **Notes:** Found 3 modules: auth, session, and legacy_token
- [x] Document current behavior with trace tools
    **Warning:** Legacy token endpoint has no tests
- [x] Create inventory of breaking vs non-breaking changes
- [ ] Get stakeholder sign-off on scope

**Notes:** Discovery revealed more complexity than expected. Legacy token is used by 2 external integrations we didn't know about.

**Warning:** Do not proceed to implementation until P1-S4 is complete.

### Phase 2: Implementation

- [ ] Create base abstraction
- [ ] Implement first concrete variant
- [ ] Implement second concrete variant
- [ ] Add configuration for edge cases
- [ ] Update all callers to use new abstraction

**Notes:** Implementation order matters - base abstraction must be complete before variants.

### Phase 3: Validation

- [ ] All lint checks pass with zero errors
- [ ] All existing tests pass
- [ ] New unit tests cover added functionality
- [ ] Manual verification of primary use case
- [ ] Manual verification of edge cases

**Blocked:** Cannot complete manual verification until test environment is provisioned (external dependency).

### Phase 4: Cleanup

- [ ] Remove deprecated code paths
- [ ] Update documentation
- [ ] Create migration guide if needed

## Completion Criteria

- Zero lint errors
- No suppression comments added (no `# type: ignore`, `# noqa`)
- All automated tests pass
- Manual verification complete
- Documentation reflects new behavior

## References

- Related issue: #123
- Design document: `docs/decisions/ADR-001-example.md`
- Previous attempt: `plans/TASK-first-attempt.md` (abandoned - captured lessons learned)
