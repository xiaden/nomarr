---
name: task-plans-guide
description: Meta-guide for creating task plan markdown files. Covers required structure, format rules, annotations, and best practices for cross-session task continuity. Load this when creating or editing files in artifacts/plans/.
---

# Task Plans Guide

Plans enable cross-session task continuity. Write them so a fresh session can read the plan and understand what's been done, what's next, and any decisions or blockers accumulated along the way.

Plans are parsed according to a strict schema. Invalid structure causes `ValueError`.

---

## Required Structure

### Minimal Template

```markdown
# Task: <Brief Title>

## Problem Statement
<What needs to be done and why. Include any context a fresh model needs.>

## Phases

### Phase 1: <Name>
- [ ] Step description
- [ ] Step description

### Phase 2: <Name>
- [ ] Step description

## Completion Criteria
<How to know when done.>
```

### Format Rules

 | Element | Pattern | Example |
 | --------- | --------- | --------- |
 | Title | `# Task: <title>` or `# <title>` | `# Task: Refactor Auth` |
 | Section | `## <name>` | `## Problem Statement` |
 | Phase | `### Phase N: <title>` | `### Phase 1: Discovery` |
 | Step (incomplete) | `- [ ] <text>` | `- [ ] Run lint_backend` |
 | Step (complete) | `- [x] <text>` | `- [x] Run lint_backend` |
 | Annotation | `**Marker:** <text>` | `**Notes:** Found 3 issues` |

**Phase numbers MUST be integers.** The parser uses regex `### Phase (\d+): (.+)`.

---

## Step Annotations

Steps can have annotations that provide context for future sessions:

```markdown
- [x] Implement auth middleware
  **Notes:** Used JWT with HS256, stored in httpOnly cookie
  **Warning:** Rate limiting not yet implemented
```

### Annotation Markers

- `**Notes:**` — Additional context, decisions made
- `**Warning:**` — Risks, gotchas, things to watch for
- `**Blocked:**` — Why this step couldn't be completed
- `**Deviation:**` — How implementation differed from plan

---

## Best Practices

### Problem Statement

Include:
- **What** needs to be done
- **Why** it matters (business/technical value)
- **Context** a fresh session needs (prior decisions, constraints)
- **Scope** boundaries (what's in, what's out)

### Phases

- Group related steps into semantic phases
- Phase names should describe outcomes, not actions
- Keep phases small enough to complete in one session when possible
- Order phases by dependency (what must come first?)

### Steps

- Each step should be atomic and verifiable
- Start with a verb (Create, Update, Delete, Verify, etc.)
- Include file paths or module names when relevant
- Mark steps complete with `- [x]` as you go
- Add annotations for decisions, warnings, or blockers

### Completion Criteria

- List measurable outcomes
- Include verification steps (lint, tests, manual checks)
- Specify what "done" looks like

---

## Example Plan

```markdown
# Task: Add User Authentication

## Problem Statement
Users need to authenticate to access protected resources. This implements JWT-based auth with httpOnly cookies for security.

Scope:
- Login/logout endpoints
- JWT token generation and validation
- Middleware for protected routes
- NOT: Registration, password reset, OAuth

## Phases

### Phase 1: Core Auth Logic
- [ ] Create auth service in `nomarr/services/auth_service.py`
- [ ] Implement JWT token generation with HS256
- [ ] Add token validation middleware
  **Notes:** Using 24-hour expiry, refresh tokens not yet implemented

### Phase 2: API Endpoints
- [ ] Add POST /api/v1/auth/login endpoint
- [ ] Add POST /api/v1/auth/logout endpoint
- [ ] Protect existing endpoints with auth middleware
  **Warning:** Need to update all existing route tests

### Phase 3: Testing
- [ ] Add unit tests for auth service
- [ ] Add integration tests for login/logout
- [ ] Verify all existing tests still pass

## Completion Criteria
- Login returns valid JWT token
- Protected endpoints reject unauthenticated requests
- All tests pass (unit + integration)
- Lint passes with zero errors
```

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Non-integer phase numbers (`### Phase 1.5:`) | Use integers only (`### Phase 1:`, `### Phase 2:`) |
| Nested steps (`  - [ ] substep`) | Flatten to top-level or use annotations |
| Missing problem statement | Always include context for fresh sessions |
| Vague steps ("Fix the thing") | Be specific: file paths, module names, expected outcomes |
| No completion criteria | List measurable outcomes and verification steps |

---

## Tool Integration

Use `plan_read` to parse and validate plan structure:

```python
plan_read(plan_name="TASK-add-auth")
```

Use `plan_complete_step` to mark steps complete with annotations:

```python
plan_complete_step(
    plan_name="TASK-add-auth",
    step_id="P1-S1",
    annotation_marker="Notes",
    annotation_text="Used JWT with HS256, stored in httpOnly cookie"
)
```

---

## Cross-Session Continuity

When resuming work on a plan:

1. Read the plan with `plan_read`
2. Check which steps are complete (`- [x]`)
3. Read annotations for context on decisions made
4. Continue from the first incomplete step
5. Update annotations as you make new decisions

The plan file is the source of truth. Annotations preserve the "why" behind decisions.
