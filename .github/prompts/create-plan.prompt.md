---
name: create-plan
description: Create a valid task plan in plans/ following the schema
agent: agent
tools:
  ['context7/*', 'nomarr_dev/analyze_project_api_coverage', 'nomarr_dev/edit_file_create', 'nomarr_dev/edit_file_insert_text', 'nomarr_dev/edit_file_replace_content', 'nomarr_dev/list_project_directory_tree', 'nomarr_dev/locate_module_symbol', 'nomarr_dev/plan_read', 'nomarr_dev/read_file_line_range', 'nomarr_dev/read_file_symbol_at_line', 'nomarr_dev/read_module_api', 'nomarr_dev/read_module_source', 'nomarr_dev/search_file_text', 'nomarr_dev/trace_module_calls', 'nomarr_dev/trace_project_endpoint', 'nomarr_dev/edit_file_replace_line_range']
---


# Task Plan Creation and Syntax Guide

**Applies when creating or editing files in `plans/`**

Plans are parsed by `mcp_code_intel.helpers.plan_md` according to `code-intel/src/mcp_code_intel/schemas/PLAN_MARKDOWN_SCHEMA.json`. Invalid structure causes `ValueError`.

---

# Task Plan Syntax

Plans are parsed by `mcp_code_intel.helpers.plan_md`. Invalid structure causes `ValueError`.

---

## Minimal Template (Single Plan)

Use for tasks with ≤2 phases and ≤12 steps total.

```markdown
# Task: <Brief Title>

## Problem Statement
<What and why. Assume reader has zero context.>

## Phases

### Phase 1: <Outcome Name>
- [ ] Concrete, verifiable step
- [ ] Another step

### Phase 2: <Outcome Name>
- [ ] Step

## Completion Criteria
- Measurable success condition
- Another condition

## References
- Related issue, ADR, or prior plan
```

---

## Format Rules

| Element | Pattern | Note |
|---------|---------|------|
| Title | `# Task: <title>` | |
| Section | `## <name>` | Any `## Header` becomes a parsed key |
| Phase | `### Phase N: <title>` | N must be sequential integer (1, 2, 3...) |
| Step | `- [ ] <text>` or `- [x] <text>` | **Must be flat — no indented checkboxes** |
| Annotation | `**Notes:**`, `**Warning:**`, `**Blocked:**` | Phase-level (after steps) or step-level (indented under step) |

**Step IDs** auto-generate as `P{phase}-S{step}` (e.g., `P1-S1`, `P2-S3`).

---

## Writing Good Steps

| ❌ Bad | ✅ Good |
|--------|---------|
| Fix auth | Implement SessionAuthMiddleware in interfaces/api/middleware/ |
| Test stuff | Verify lint_project_backend passes on nomarr/services |
| Add imports | Create config_service module with ConfigService class |
| Make it work | Update all callers of get_library() to use new signature |

**Steps must be:** Actionable (clear action), Verifiable (can confirm done), Atomic (one outcome).

**Phases are semantic outcomes** ("Discovery", "Validation"), not file names ("Edit file 1").

---

## When to Split

Split into parent→child plans if ANY condition is true:
- More than 2 phases
- More than 12 steps total
- `plan_read` returns a resource link instead of inline content

**Resource link = absolute trigger.** If you see `Large tool result written to file...`, the plan is too large. Split immediately.

---

## Split Architecture

**Maximum 2 levels.** One parent orchestrator + multiple child plans. Never nest orchestrators.

### Parent (Orchestrator)

```markdown
# Task: Feature Name (Orchestrator)

## Problem Statement
High-level overview. Child plans contain details.

## Phases

### Phase 1: Orchestration
- [ ] TASK-feature-A-discovery complete
- [ ] TASK-feature-B-implementation complete
    **Blocked:** Requires A sign-off
- [ ] TASK-feature-C-validation complete

## Completion Criteria
- All child plans completed

## References
- `plans/TASK-feature-A-discovery.md`
- `plans/TASK-feature-B-implementation.md`
- `plans/TASK-feature-C-validation.md`
```

**Parent rules:**
- Single phase named "Orchestration"
- Steps are child completion conditions, not implementation actions
- Mark step complete when linked child reaches 100%

### Child

```markdown
# Task: Feature Name - Discovery

## Problem Statement
Specific scope. Context for fresh models.

**Parent:** `TASK-feature.md`
**Prerequisite:** None (or required sibling)

## Phases

### Phase 1: Analysis
- [ ] Step
- [ ] Step

### Phase 2: Assessment
- [ ] Step

## Completion Criteria
- Criteria

## References
- Parent: `plans/TASK-feature.md`
- Siblings: B-implementation, C-validation
```

**Child rules:**
- Title: `<Parent Feature> - <Child Outcome>`
- Problem Statement includes parent reference and prerequisites
- Can have multiple phases

### Naming Convention

```
TASK-<feature>.md                 (orchestrator)
TASK-<feature>-A-<outcome>.md     (first child)
TASK-<feature>-B-<outcome>.md     (second child)
```

### If a Child Is Still Too Large

**Add siblings, don't nest deeper.**

```
Before: TASK-feature-A-discovery.md triggers split
After:  TASK-feature-A1-discovery-scope.md
        TASK-feature-A2-discovery-assess.md
```

Parent gains additional steps. Hierarchy stays at 2 levels.

---

## Parser Rejection Rules

### Nested Steps ❌
```markdown
- [ ] Create files
  - [ ] Create auth.py    ← REJECTED: indented checkbox
```
Fix: Unnest as flat steps, move to `**Notes:**`, or split into phases.

### Non-Sequential Phases ❌
```markdown
### Phase 1: Discovery
### Phase 3: Implementation   ← REJECTED: skipped 2
```

### Invalid Phase Format ❌
```markdown
### Phase One: Discovery      ← REJECTED: must be integer
### Phase 1 - Discovery       ← REJECTED: must use colon
```

---

## Validation

**Always run `plan_read(plan_name)` after creating a plan.** Fix errors before proceeding. For split plans, validate parent and all children independently.

---

## Complete Examples

See `plans/examples/`:
- `TASK-example-comprehensive.md` — Parent orchestrator
- `TASK-example-A-discovery.md` through `D-cleanup.md` — Child plans

---

## Common Mistakes

| Don't | Do Instead |
|-------|------------|
| Indent checkboxes | Flat steps only |
| Skip phase numbers (1→3) | Sequential: 1, 2, 3 |
| `### Phase One:` | `### Phase 1:` |
| Vague steps ("fix auth") | Concrete ("Implement AuthMiddleware in X") |
| Skip problem statement | Always include context |
| Manual checkbox edits | Use `plan_complete_step` |
| Micro-steps ("add import") | Meaningful units |
| Multiple orchestrator phases | Single "Orchestration" phase |
| Nest 3+ levels | Add siblings (A1, A2) instead |
