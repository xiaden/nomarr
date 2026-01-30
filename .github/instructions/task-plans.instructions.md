---
name: Task Plans
description: Guidelines for creating and maintaining task/plan files for complex operations
applyTo: docs/dev/plans/**
---

# Task Plan Files

**Purpose:** Track progress on multi-step operations that may exceed context window limits.

These files are written by models, for models. They survive context boundaries and provide continuity across sessions.

---

## When to Create a Task File

Create a task file when:
- The operation has 5+ distinct steps
- You're modifying 3+ files with interdependencies
- The task involves architectural changes across layers
- You're uncertain whether you'll complete in one context window

**Don't create task files for:**
- Single-file fixes
- Simple refactors you can verify with `lint_backend`
- Tasks you've already nearly completed

---

## File Naming

```
TASK-<verb>-<subject>.md

Examples:
TASK-refactor-library-service.md
TASK-migrate-auth-to-sessions.md
TASK-add-batch-processing.md
```

---

## Required Structure

```markdown
# Task: <Brief Title>

## Problem Statement
<What needs to be done and why. Include any context a fresh model needs.>

## Phases

### Phase 1: <Name>
- [ ] Step description
- [ ] Step description
- [x] Completed step

**Notes:** <Issues encountered, decisions made, blockers>

### Phase 2: <Name>
- [ ] Step description

## Completion Criteria
<How to know when done. Usually: lint passes, tests pass, specific behavior verified>
```

---

## Updating Task Files

**Mark progress immediately.** Don't batch checkbox updates.

When completing a step:
1. Mark the checkbox `[x]`
2. Add notes if you encountered something unexpected
3. Save before moving to next step

When hitting a blocker:
1. Add a **Blocked:** note under the phase
2. Explain what's blocking and what information is needed
3. Continue with unblocked phases if possible

---

## Reading Task Files (New Context)

If you're a fresh context picking up a task file:

1. Read the entire file first
2. Identify which phase is in progress (has mix of checked/unchecked)
3. Read notes carefully—they contain decisions already made
4. Resume from the first unchecked item in the active phase
5. Run `lint_backend` before making changes to understand current state

**Don't re-do completed work.** Trust the checkboxes unless lint fails.

---

## Example

```markdown
# Task: Remove Dead Component Injection

## Problem Statement
LibraryService has dead type stubs from an abandoned component injection refactor.
These cause mypy `no-redef` errors. Need to remove stubs and fix method calls.

## Phases

### Phase 1: Identify Dead Code
- [x] Run lint_backend to find all errors
- [x] Use discover_api on LibraryService mixins
- [x] Confirm component attributes are never assigned

**Notes:** Found 4 dead stubs in admin.py, 2 in scan.py. All were shadows.

### Phase 2: Remove Stubs and Fix Calls
- [x] Remove stubs from admin.py
- [x] Change self.component.method() to self.db.table.method()
- [x] Remove stubs from scan.py  
- [x] Fix scan.py method calls

**Notes:** get_library_counts needed full rewrite, was calling non-existent component.

### Phase 3: Validate
- [x] lint_backend passes on nomarr/services
- [x] lint_backend passes on full nomarr/

## Completion Criteria
- Zero lint errors in nomarr/
- No type: ignore comments added
```

---

## Anti-Patterns

**Don't:**
- Create overly granular steps ("add import", "add function", "add docstring")
- Leave notes vague ("had issues here")
- Skip the problem statement
- Create task files for work you're about to finish anyway

**Do:**
- Group related work into meaningful steps
- Include specific error messages or file paths in notes
- Explain *why* when noting a decision
- Create early if you sense complexity growing

