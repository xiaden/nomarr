---
name: create-plan
description: Create a valid task plan in plans/ following the schema
agent: agent
tools:
  ['context7/*', 'nomarr_dev/analyze_project_api_coverage', 'nomarr_dev/edit_file_create', 'nomarr_dev/edit_file_insert_text', 'nomarr_dev/edit_file_replace_content', 'nomarr_dev/list_project_directory_tree', 'nomarr_dev/locate_module_symbol', 'nomarr_dev/plan_read', 'nomarr_dev/read_file_line_range', 'nomarr_dev/read_file_symbol_at_line', 'nomarr_dev/read_module_api', 'nomarr_dev/read_module_source', 'nomarr_dev/search_file_text', 'nomarr_dev/trace_module_calls', 'nomarr_dev/trace_project_endpoint', 'nomarr_dev/edit_file_replace_by_content', 'nomarr_dev/edit_file_move_by_content']
---


# Task Plan Creation and Syntax Guide

**Applies when creating or editing files in `plans/`**

Plans are parsed by `mcp_code_intel.helpers.plan_md` according to `code-intel/src/mcp_code_intel/schemas/PLAN_MARKDOWN_SCHEMA.json`. Invalid structure causes `ValueError`.

---

# Task Plan Syntax

Plans are parsed by `mcp_code_intel.helpers.plan_md`. Invalid structure causes `ValueError`.

---

## Template

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

## Splitting Large Tasks

Split a plan into sequential parts if ANY condition is true:
- More than 2 phases
- More than 12 steps total
- `plan_read` returns a resource link instead of inline content

**Resource link = absolute trigger.** If you see `Large tool result written to file...`, the plan is too large. Split immediately.

### How to Split

Create independent plans with letter-suffixed names. Each plan is self-contained with its own Problem Statement, Phases, and Completion Criteria. **No orchestrator/parent plan.**

```
TASK-<feature>-A-<outcome>.md     (first part)
TASK-<feature>-B-<outcome>.md     (second part)
TASK-<feature>-C-<outcome>.md     (third part)
```

The naming convention carries the sequencing: A before B before C.

Each plan should include:
- Full Problem Statement (assume reader has zero context)
- `**Prerequisite:** TASK-<feature>-A-<outcome>` if it depends on a prior part
- Its own Completion Criteria (not "all parts done")
- References to sibling plans for navigation

### If a Part Is Still Too Large

**Add siblings, don't nest deeper.**

```
Before: TASK-feature-A-discovery.md triggers split
After:  TASK-feature-A1-discovery-scope.md
        TASK-feature-A2-discovery-assess.md
```

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

**Always run `plan_read(plan_name)` after creating a plan.** Fix errors before proceeding.

---

## Complete Examples

See `plans/examples/`:
- `TASK-example-A-discovery.md` through `D-cleanup.md` — Split plan set

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
| Create orchestrator plans | Just use A→B→C naming |
