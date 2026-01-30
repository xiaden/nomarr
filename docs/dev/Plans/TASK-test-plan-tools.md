# Task: Test Plan Tools

## Problem Statement
Verify that the plan management MCP tools work correctly.

**Warning:** This plan is for testing only - do not use as a template.
**Warning:** Previous context hit limit mid-task, some steps may need re-verification.

## Phases

### Phase 1: read_plan
- [ ] Fresh plan (no progress)
- [x] Partial progress
- [ ] Complete plan

**Notes:** This phase tests the read_plan tool. We discovered that active_phase must always be included when there are incomplete steps, not just after progress. The original spec was wrong - you need to know where to start even on a fresh plan.

### Phase 2: get_steps
- [ ] Default (active phase)
- [ ] Specific phase

**Notes:** get_steps is for focused work on a single phase. It returns the phase's steps plus any notes. Use this when you know which phase you're in and don't need the full plan context.

### Phase 3: complete_step
- [ ] Basic completion
- [ ] With note
- [ ] Phase transition

**Notes:** complete_step was initially too sparse - returning just the step ID. Fixed to return id + text + notes so the next step is actionable without another tool call.

## Completion Criteria
- All tools tested with realistic data
