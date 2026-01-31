---
name: Task Plans
description: Guidelines for creating and maintaining task/plan files for complex operations
applyTo: docs/dev/plans/**
---

# Task Plan Files

**Purpose:** Track progress on multi-step operations that may exceed context window limits.

These files are written by models, for models. They survive context boundaries and provide continuity across sessions.

---

## When to Create a Plan

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

## File Naming and Location

Plans go in `docs/dev/plans/` with this naming convention:

```
TASK-<verb>-<subject>.md

Examples:
TASK-refactor-library-service.md
TASK-migrate-auth-to-sessions.md
TASK-add-batch-processing.md
```

The **plan name** for MCP tools is the filename without `.md` extension.

---

## Plan Structure

The MCP parser expects specific patterns. Follow this exactly.

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
|---------|---------|---------|
| Title | `# Task: <title>` or `# <title>` | `# Task: Refactor Auth` |
| Section | `## <name>` | `## Problem Statement` |
| Phase | `### Phase N: <title>` | `### Phase 1: Discovery` |
| Step (incomplete) | `- [ ] <text>` | `- [ ] Run lint_backend` |
| Step (complete) | `- [x] <text>` | `- [x] Run lint_backend` |
| Annotation | `**Marker:** <text>` | `**Notes:** Found 3 issues` |

**Phase numbers MUST be integers.** The parser uses regex `### Phase (\d+): (.+)`.

**Step IDs are auto-generated** as `P<phase>-S<step>`:
- Phase 1, Step 1 → `P1-S1`
- Phase 2, Step 3 → `P2-S3`

### Supported Sections

Any `## Header` becomes a key in the parsed output. Common sections:
- `Problem Statement` - Context for fresh models (can be multi-line)
- `Completion Criteria` - Success conditions (parsed as bullet list if formatted that way)
- `References` - Related issues, ADRs, previous attempts

### Annotations (Phase-Level vs Step-Level)

**Phase-level annotations** go after the steps, before the next phase:

```markdown
### Phase 1: Discovery
- [x] Find all auth patterns
- [x] Document endpoints

**Notes:** Found 3 patterns: session, API key, legacy token.
**Warning:** Legacy token has no tests.
```

**Step-level annotations** are indented under the step (created by `complete_step`):

```markdown
- [x] Remove legacy auth
    **Notes:** Had to update 12 callers
    **Warning:** One caller in deprecated endpoint, added TODO
```

Both are parsed and returned by `get_steps`.

---

## MCP Tools Reference

Three tools manage plans. Use these instead of manual edits.

### `read_plan(plan_name)`

**Purpose:** Get full plan structure as JSON.

**Returns:**
```json
{
  "title": "Refactor Auth",
  "Problem Statement": "...",
  "Completion Criteria": ["lint passes", "tests pass"],
  "phases": [
    {
      "number": 1,
      "title": "Discovery",
      "steps": [
        {"id": "P1-S1", "text": "Find auth patterns", "done": true},
        {"id": "P1-S2", "text": "Document endpoints"}
      ],
      "Notes": "Found 3 patterns...",
      "Warning": "Legacy has no tests"
    }
  ],
  "next": "P1-S2"
}
```

**Key fields:**
- `next` - ID of first incomplete step (where to resume)
- `phases[].steps[].done` - Only present if `true`
- Phase-level annotations appear as keys on the phase object

**Use when:** Starting work on a plan, need full context.

---

### `get_steps(plan_name, phase_name=None)`

**Purpose:** Get focused view of one phase.

**Parameters:**
- `plan_name` - Filename without `.md`
- `phase_name` - Phase title (e.g., `"Discovery"`). If omitted, returns the **active phase** (first with incomplete steps).

**Returns:**
```json
{
  "title": "Discovery",
  "steps": [
    {"id": "P1-S1", "text": "Find auth patterns", "done": true},
    {"id": "P1-S2", "text": "Document endpoints"}
  ],
  "Notes": "Found 3 patterns...",
  "Warning": "Legacy has no tests",
  "next": "P1-S2"
}
```

**Use when:** You know which phase you're in and want just its details.

---

### `complete_step(plan_name, step_id, annotation=None)`

**Purpose:** Mark a step complete. Optionally attach context.

**Parameters:**
- `plan_name` - Filename without `.md`
- `step_id` - Step ID in `P<n>-S<m>` format
- `annotation` - Optional `(marker, text)` tuple

**Behavior:**
1. Changes `- [ ]` to `- [x]` on the step's line
2. If annotation provided, inserts indented `**Marker:** text` under the step
3. If same annotation already exists, appends to it (idempotent)
4. Returns the next incomplete step

**Returns:**
```json
{
  "completed": "P1-S2",
  "was_already_complete": false,
  "annotation_written": true,
  "next": {"step_id": "P1-S3", "phase_title": "Discovery", "text": "..."}
}
```

**Annotation markers:**
| Marker | When to use |
|--------|-------------|
| `Notes` | General observations, decisions made |
| `Warning` | Issues future contexts should know about |
| `Blocked` | Why work cannot proceed on this step |

**Examples:**
```python
# Simple completion
complete_step("TASK-auth", "P1-S2")

# With annotation
complete_step("TASK-auth", "P1-S3", annotation=("Notes", "Used middleware pattern per ADR-007"))

# Marking blocked
complete_step("TASK-auth", "P2-S1", annotation=("Blocked", "Need API key rotation before removing legacy"))
```

---

## Workflows

### Creating a New Plan

1. Create file in `docs/dev/plans/TASK-<verb>-<subject>.md`
2. Write problem statement (assume reader has no context)
3. Break work into phases (logical groupings, not 1:1 with files)
4. Write steps as actionable items (verifiable, not "work on X")
5. Add completion criteria (how to know when done)

### Working a Plan

1. Call `read_plan` to get overview and `next` step
2. Call `get_steps` if you need phase details
3. Do the work for one step
4. Call `complete_step` with the step ID
5. Add annotation if anything unexpected happened
6. Repeat from step 3

### Resuming a Plan (New Context)

1. Call `read_plan` to see where you left off
2. Check `next` field for the resume point
3. Read any `Warning` or `Blocked` annotations from prior phases
4. Run `lint_backend` to verify current state
5. Continue from `next`

**Trust the checkboxes.** Don't re-do completed work unless lint fails.

### Handling Blockers

If a step can't be completed:

```python
complete_step("TASK-auth", "P2-S3", annotation=("Blocked", "Need user confirmation on breaking change"))
```

Then either:
- Skip to next unblocked phase
- Document in problem statement what's needed
- End session with clear handoff

---

## Example: Complete Plan

```markdown
# Task: Unify Authentication Middleware

## Problem Statement
Current auth is split across 3 patterns: session cookies, API keys, and legacy tokens.
Need unified middleware that handles all patterns with consistent error responses.

**Context:** Legacy token auth (`check_token`) has no tests and unknown consumers.
Approach: add deprecation logging first, remove after 2 weeks of monitoring.

## Phases

### Phase 1: Discovery
- [x] Run discover_api on auth modules
    **Notes:** 3 modules: session_auth, api_key_auth, legacy_auth
- [x] Map current flow with trace_endpoint
- [x] Document all endpoints using each pattern
    **Notes:** 47 endpoints use session, 12 use API key, 1 uses legacy

**Warning:** Legacy endpoint /api/v1/status has external consumers (Grafana integration)

### Phase 2: Design
- [x] Create AuthMiddleware base class
- [x] Implement SessionAuthMiddleware
- [x] Implement ApiKeyAuthMiddleware
- [ ] Add bypass config for public routes

### Phase 3: Migration
- [ ] Update web routes
- [ ] Update API routes
- [ ] Add deprecation logging to legacy
- [ ] Update tests

**Blocked:** Cannot remove legacy until deprecation period complete

### Phase 4: Validation
- [ ] lint_backend passes
- [ ] All auth tests pass
- [ ] Manual test: web login
- [ ] Manual test: API key auth
- [ ] Manual test: invalid creds → 401

## Completion Criteria
- Zero lint errors
- No type: ignore comments
- All auth flows verified
- Legacy deprecated (not removed - blocked)
```

---

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| Overly granular steps ("add import") | Group into meaningful units ("implement middleware") |
| Vague notes ("had issues") | Specific context ("mypy error on line 42, fixed with cast") |
| Skip problem statement | Write for a model with no context |
| Create plan for nearly-done work | Just finish it |
| Manual checkbox edits | Use `complete_step` |
| Re-verify completed steps | Trust checkboxes unless lint fails |
| Leave Blocked without explanation | Always say what's needed to unblock |

