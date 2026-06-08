---
name: dispatching-support-debugger
description: Template for dispatching Support-Debugger to diagnose failures and unexpected behavior.
---

# Dispatching Support-Debugger

Use this skill when you need Support-Debugger to diagnose a failure, runtime error, lint error, or unexpected behavior.

## When to Dispatch

- When tests fail and the root cause is unclear
- When runtime errors occur during execution
- When lint errors appear and the cause is not obvious
- When behavior doesn't match expectations
- When Exec-Manager encounters a blocker it cannot resolve

## Dispatch Template

```
Diagnose this failure:

Context files:
- {plan file being executed, if applicable}
- {contracts file, if applicable}

failure:
  type: TEST_FAILURE | RUNTIME_ERROR | LINT_ERROR | UNEXPECTED_BEHAVIOR
  symptom: "{describe what went wrong}"
  errorMessage: "{full error text}"
  location:
    file: "{file path if known}"
    line: {line number if known}
```

## Required Fields

- `type`: One of `TEST_FAILURE`, `RUNTIME_ERROR`, `LINT_ERROR`, `UNEXPECTED_BEHAVIOR`
- `symptom`: Human-readable description of what went wrong
- `errorMessage`: Full error text (copy-paste from logs)
- `location.file`: File path if known (omit if unknown)
- `location.line`: Line number if known (omit if unknown)

## Expected Output

Support-Debugger returns:
- `rootCause`: Explanation of what caused the failure
- `fixComplexity`: One of `SIMPLE`, `NEEDS_PLAN`, `INCONCLUSIVE`
- `suggestedFix`: Concrete fix suggestion (if complexity is SIMPLE)

## Routing Debugger Output

| `fixComplexity` | Action |
|-----------------|--------|
| `SIMPLE` | Spawn **Exec-Fixer** with the debugger's `suggestedFix` and affected files. Then run full QA review. |
| `NEEDS_PLAN` | Spawn **Exec-Planner** (AMEND) with the debugger's `rootCause.explanation` as the amendment reason. Re-execute affected phases. Then full QA review. |
| `INCONCLUSIVE` | Escalate to Director with the full debugger report. |

## After Fix

Always run full QA review after any fix, not just the fixed items.
