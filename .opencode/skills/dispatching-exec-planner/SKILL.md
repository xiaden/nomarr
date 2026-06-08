---
name: dispatching-exec-planner
description: Templates for dispatching Exec-Planner to create, amend, or reorder implementation plans.
---

# Dispatching Exec-Planner

Use this skill when you need Exec-Planner to create an implementation plan, amend an existing plan, or reorder plans.

## When to Dispatch

- **CREATE**: When a design document needs to be broken into implementation plans
- **AMEND**: When a plan needs to be updated due to PLANNING_GAP issues or new requirements
- **REORDER**: When plans are out of sequence and need reordering

---

## CREATE: Initial Planning

```
Create an implementation plan from design document: [DD_PATH]

Context files to read:
- [DD_PATH]  — design document
- [CONTRACTS_PATH]  — contracts ledger (if multi-part feature)

Librarian briefing: [paste briefing or "see attached context"]
Key constraints: [key constraints from Librarian/PatternEnforcer]
```

### Required Fields

- `[DD_PATH]`: Path to the design document
- `[CONTRACTS_PATH]`: Path to contracts ledger (omit if not a multi-part feature)
- `[paste briefing or "see attached context"]`: Librarian's briefing
- `[key constraints]`: Critical constraints from Librarian/PatternEnforcer

---

## AMEND: Plan Amendment

Use when QA-Reviewer flags PLANNING_GAP issues, or when Support-Debugger identifies that a fix requires plan changes.

```
Amend plan TASK-{feature}-{letter}-{title}.

Context files:
- artifacts/plans/pending/TASK-{feature}-{letter}-{title}.md  (existing plan)
- artifacts/designs/parts/{feature}/CONTRACTS.md
- artifacts/designs/parts/{feature}/README.md

task:
  type: AMEND
  plan: "TASK-{feature}-{letter}-{title}"
  reason: "{paste PLANNING_GAP detail from review report}"
```

### Required Fields

- `TASK-{feature}-{letter}-{title}`: The plan to amend
- `reason`: The PLANNING_GAP detail from the review report or debugger's root cause

### After AMEND

Re-execute affected phases, then run full QA review.

---

## REORDER: Plan Reordering

Use when plans are out of sequence (e.g., A, B, E, C, D instead of A, B, C, D, E).

```
Reorder plans for feature {feature}.

Context files:
- artifacts/plans/pending/  (all plan files for this feature)
- artifacts/designs/parts/{feature}/CONTRACTS.md
- artifacts/designs/parts/{feature}/README.md

task:
  type: REORDER
  feature: "{feature}"
  insertion:
    newPlan: "TASK-{feature}-{letter}-{title}"  (the out-of-sequence plan)
    insertAfter: "{letter}"                      (letter of the plan it should follow)
  reason: "{why this plan must precede the ones after it}"
```

### Required Fields

- `{feature}`: The feature slug
- `newPlan`: The out-of-sequence plan
- `insertAfter`: The letter of the plan it should follow
- `reason`: Why this plan must precede the ones after it

### After REORDER

**Do not execute any plan until Exec-Planner reports DONE.**

---

## Expected Output

Exec-Planner returns:
- **CREATE**: One or more plan files in `artifacts/plans/pending/`
- **AMEND**: Updated plan file with new/amended phases
- **REORDER**: Confirmation of new plan order

All outputs include `status: DONE` when complete.
