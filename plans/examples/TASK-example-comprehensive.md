# Task: Comprehensive Example (Orchestrator)

## Problem Statement

This is a reference demonstrating **split planning with orchestration**. When a task exceeds the split threshold (>2 phases OR >12 steps), break it into child plans and use a parent plan to track overall progress.

**Why split?**

- Prevents token overflow in chat/tool payloads
- Each child plan is independently executable and verifiable
- Parent plan shows forest-level progress; child plans show tree-level detail

**Split triggers (any one):**

- More than 2 phases
- More than 12 steps total
- Combined content length is "long"

**Context for fresh models:** Read this parent plan first to understand overall scope. Then read the specific child plan for your current phase. Complete child plans fully before marking the parent step done.

## Phases

### Phase 1: Orchestration

- [x] TASK-example-A-discovery complete
    **Notes:** Discovery revealed legacy token used by 2 external integrations. See child plan for full findings.
- [ ] TASK-example-B-implementation complete
    **Blocked:** Waiting on P1-S1 stakeholder sign-off (in discovery plan)
- [ ] TASK-example-C-validation complete
- [ ] TASK-example-D-cleanup complete

**Notes:** Steps in this phase are outcome conditions, not actions. Mark complete when the linked child plan reaches 100%.

## Completion Criteria

- All child plans (A through D) fully completed
- Zero lint errors across all changes
- No suppression comments added
- Manual verification documented in validation plan

## References

- `plans/examples/TASK-example-A-discovery.md`
- `plans/examples/TASK-example-B-implementation.md`
- `plans/examples/TASK-example-C-validation.md`
- `plans/examples/TASK-example-D-cleanup.md`
- Related issue: #123
- Design document: `docs/decisions/ADR-001-example.md`
