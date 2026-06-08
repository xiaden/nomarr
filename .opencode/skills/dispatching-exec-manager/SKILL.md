---
name: dispatching-exec-manager
description: Template for dispatching Exec-Manager to execute an implementation plan.
---

# Dispatching Exec-Manager

Use this skill when you need Exec-Manager to execute an implementation plan.

## When to Dispatch

- When a plan is ready for implementation
- After Exec-Planner has created the plan
- After RnD-Manager has produced a design document and Exec-Planner has planned it

## Dispatch Template

```
Execute plan [PLAN_PATH].

**Your job is to spawn your workers:**
- Spawn Exec-Executor for EACH phase in order (one spawn per phase, never bundle)
- Spawn QA-Reviewer after ALL phases complete
- Spawn Exec-Fixer for MINOR issues found by QA-Reviewer
Do NOT implement code yourself.

Context files to read:
- [PLAN_PATH]  — the plan
- [CONTRACTS_PATH]  — contracts ledger (omit if not a multi-part feature)
- [DESIGN_DOC_PATH]  — design document

task:
  plan: "TASK-{feature}-{letter}-{title}"
  startPhase: 1
  reviewRequired: true
```

## Required Fields

- `[PLAN_PATH]`: Path to the plan file
- `[CONTRACTS_PATH]`: Path to contracts ledger (omit if not a multi-part feature)
- `[DESIGN_DOC_PATH]`: Path to the design document
- `plan`: The plan identifier (e.g., "TASK-feature-A-scope")
- `startPhase`: Which phase to start from (usually 1)
- `reviewRequired`: Must be `true` to enforce QA gate

## Key Instruction

The bolded worker-spawn instructions are **required** — they remind Exec-Manager that it dispatches workers, not implements code itself.

## Expected Output

Exec-Manager returns:
- `status: DONE` when all phases complete and QA-Reviewer passes
- `status: BLOCKED` when a blocker cannot be resolved internally
- `status: ESCALATE` when Director input is needed

The output includes:
- Artifacts created/modified/deleted
- Annotations from each phase
- QA review status (mandatory for DONE)
- Test and docs analyzer status

## QA Gate

Exec-Manager **must not** return `status: DONE` without `qaReview.status: PASS`. If QA-Reviewer hasn't run or hasn't passed, the status must be `BLOCKED` or `ESCALATE`.
