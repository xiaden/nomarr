---
name: dispatching-rnd-manager
description: Template for dispatching RnD-Manager to design a feature or conduct R&D work.
---

# Dispatching RnD-Manager

Use this skill when you need RnD-Manager to design a feature or conduct research and analysis.

## When to Dispatch

- When a feature needs design before implementation
- When you need options, tradeoffs, or analysis
- When you need a design document created

## Dispatch Template

```
Design [FEATURE].

**Your job is to spawn your workers:**
- Spawn Support-Librarian if you need artifact context
- Spawn RnD-DDAuthor to create the formal design document
- Spawn RnD-Architect, RnD-Ideator, RnD-Estimator as needed for analysis
Do NOT create the design document yourself.

Requirements: [user requirements or path to requirements doc]
Librarian briefing: [paste briefing or "see attached context"]
Prior decisions to respect: [key constraints from Librarian]
```

## Required Fields

- `[FEATURE]`: The feature name or description
- `[user requirements or path to requirements doc]`: What needs to be built
- `[paste briefing or "see attached context"]`: Librarian's briefing (or note that context is attached)
- `[key constraints from Librarian]`: Critical constraints that must be respected

## Key Instruction

The bolded worker-spawn instructions are **required** — they remind RnD-Manager that it dispatches workers, not creates documents itself.

## Expected Output

RnD-Manager returns:
- A design document (created by RnD-DDAuthor)
- Recommendations and tradeoffs
- Effort estimates
- Scope validation (via Support-PatternEnforcer)
