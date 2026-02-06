---
name: create-plan
description: Create a valid task plan in plans/ following the schema
agent: agent
tools:
  ['context7/*', 'nomarr_dev/analyze_project_api_coverage', 'nomarr_dev/edit_file_create', 'nomarr_dev/edit_file_insert_text', 'nomarr_dev/edit_file_replace_content', 'nomarr_dev/list_project_directory_tree', 'nomarr_dev/locate_module_symbol', 'nomarr_dev/plan_read', 'nomarr_dev/read_file_line_range', 'nomarr_dev/read_file_symbol_at_line', 'nomarr_dev/read_module_api', 'nomarr_dev/read_module_source', 'nomarr_dev/search_file_text', 'nomarr_dev/trace_module_calls', 'nomarr_dev/trace_project_endpoint', 'nomarr_dev/edit_file_replace_line_range']
---


# Task Plan Creation and Syntax Guide

**Auto-applies when creating or editing files in `plans/`**

Plans are parsed by `mcp_code_intel.helpers.plan_md` according to `code-intel/src/mcp_code_intel/schemas/PLAN_MARKDOWN_SCHEMA.json`. Invalid structure causes `ValueError`.

---

## Schema Definition

Plans are JSON-serializable with this structure:

```json
{
  "title": "string (required)",
  "Problem Statement": "string or array (recommended)",
  "phases": [
    {
      "number": 1,
      "title": "string",
      "steps": [
        {
          "id": "P1-S1",
          "text": "string",
          "done": false,
          "annotations": {
            "Notes": "string or array (pure bullets → array, mixed → string)",
            "Warning": "string or array",
            "Blocked": "string or array"
          }
        }
      ],
      "annotations": {}
    }
  ],
  "Completion Criteria": "string or array (recommended)",
  "References": "string or array (optional)"
}
```

**Critical rules:**
- Steps MUST be flat (no nesting/children)
- Phase numbers MUST be sequential integers starting at 1
- Step IDs auto-generated as `P{phase}-S{index}`
- **Annotations:** Pure bullet lists → arrays; mixed content (text + bullets) → string with `\n`

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
|---------|---------|---------|
| Title | `# Task: <title>` or `# <title>` | `# Task: Refactor Auth` |
| Section | `## <name>` | `## Problem Statement` |
| Phase | `### Phase N: <title>` | `### Phase 1: Discovery` |
| Step (incomplete) | `- [ ] <text>` | `- [ ] Run lint_project_backend` |
| Step (complete) | `- [x] <text>` | `- [x] Run lint_project_backend` |
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

**Step-level annotations** are indented under the step (created by `plan_complete_step`):

```markdown
- [x] Remove legacy auth
    **Notes:** Had to update 12 callers
    **Warning:** One caller in deprecated endpoint, added TODO
```

These are parsed and returned by `plan_read`.

---

## Writing Quality Steps

**Good steps are:**
- **Actionable** - Clear what needs doing (`Run lint_project_backend on helpers/`)
- **Verifiable** - Can confirm completion (`All tests pass`, not "improve tests")
- **Atomic** - One logical outcome per step
- **Appropriately scoped** - Not too granular ("add import") or vague ("fix auth")

**Examples:**

| ❌ Bad | ✅ Good |
|--------|---------|
| Work on auth middleware | Implement SessionAuthMiddleware class in interfaces/api/middleware/ |
| Fix issues | Resolve mypy errors in persistence/models/library.py |
| Add imports | Create config_service module with ConfigService class |
| Test stuff | Verify lint_project_backend passes on nomarr/services |
| Make it work | Update all callers of get_library() to use new signature |

**Phase Design:**
- Phases represent **semantic outcomes**, not file boundaries
- Example: "Discovery", "Implementation", "Validation" not "Edit file 1", "Edit file 2"
- Group related steps by what they accomplish, not how they're implemented

---

## Parser Rejection Rules

The parser will **reject with `ValueError`** if:

### Nested Steps (CRITICAL)
```markdown
### Phase 1: Setup
- [ ] Create files
  - [ ] Create auth.py    # ❌ Indented checkbox = NESTED STEP
```

**Error message:** `"Plan contains nested steps, which are not allowed per PLAN_MARKDOWN_SCHEMA.json"`

**Why rejected:** Nested steps create ambiguous execution models. If substeps are needed:
- Distinct outcomes → unnest as separate flat steps
- Implementation details → convert to `**Notes:**` annotation
- Need grouping → create new phase

### Non-Sequential Phase Numbers
```markdown
### Phase 1: Discovery
### Phase 3: Implementation    # ❌ Skipped Phase 2
```

Parser expects phases numbered 1, 2, 3... with no gaps.

### Invalid Phase Header Format
```markdown
### Phase One: Discovery       # ❌ Must be integer
### Phase 1 - Discovery        # ❌ Must use colon
```

**Required:** `### Phase \d+: <title>` (regex pattern enforced)

---

## Validating Plans After Creation

**Always validate before executing:**

After writing or modifying a plan, use `plan_read` to verify it parses correctly:

```python
plan_read(plan_name)
```

**What this catches:**
- Invalid phase numbers (1.5, A, 1a, non-sequential)
- Malformed checkboxes or nested steps
- Schema violations

**If `plan_read` returns an error:**
- Fix the plan structure immediately
- Re-validate with `plan_read` again
- Only then proceed to execution with `plan_complete_step`

**Example validation flow:**
```python
# After creating plans/TASK-new-feature.md
result = plan_read("TASK-new-feature")

if "error" in result:
    # Fix the plan file, then validate again
    print(f"Plan validation failed: {result['message']}")
else:
    # Plan is valid, safe to execute
    print(f"Plan validated: {result['title']}")
```

**Why this matters:** Parse errors block both reading and step completion. Catching structural issues immediately prevents wasted work on unexecutable plans.

---

## Complete Example

See `plans/examples/TASK-example-comprehensive.md` for a fully-formed plan demonstrating all patterns.

**Key characteristics of a good plan:**
- Problem statement assumes reader has no context
- Phases are outcome-oriented ("Validation" not "Phase 3")
- Steps are concrete and verifiable
- Completion criteria are measurable
- Annotations capture decisions, blockers, warnings

---

## Common Mistakes

| Don't | Do Instead | Why |
|-------|------------|-----|
| Indent checkboxes | Keep all steps flat | Parser rejects nested structure |
| Skip phase numbers (1→3) | Sequential numbering | Parser validation |
| Use `### Phase One:` | Use `### Phase 1:` | Regex requires integer |
| Write vague steps ("fix auth") | Concrete outcomes ("Implement AuthMiddleware in interfaces/api/") | Steps must be verifiable |
| Skip problem statement | Context for fresh models | Cross-session continuity |
| Manual checkbox edits | Use `plan_complete_step` | Preserves annotations |
| Steps like "add import X" | Group into meaningful units | Avoid over-granularity |

