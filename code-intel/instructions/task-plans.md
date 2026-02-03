---
name: Task Plans
description: Valid syntax for task plan markdown files parsed by mcp_code_intel
applyTo: plans/**
---

# Task Plans

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

**Step-level annotations** are indented under the step (created by `plan_complete_step`):

```markdown
- [x] Remove legacy auth
    **Notes:** Had to update 12 callers
    **Warning:** One caller in deprecated endpoint, added TODO
```

These are parsed and returned by `plan_read`.

#### Annotation Format in Parsed Output

Annotations are returned as either **strings** or **arrays** depending on content:

- **Pure bullet lists** → Array of strings:
  ```markdown
  **Notes:**
  - First point
  - Second point
  ```
  Parses to: `{"Notes": ["First point", "Second point"]}`

- **Mixed content** (text + bullets, or multiple blocks) → String with `\n`:
  ```markdown
  **Notes:** Context paragraph.
  - Detail 1
  - Detail 2
  ```
  Parses to: `{"Notes": "Context paragraph.\n- Detail 1\n- Detail 2"}`

- **Multiple markers with same name** → Combined into array:
  ```markdown
  **Notes:** First observation
  **Notes:** Second observation
  ```
  Parses to: `{"Notes": ["First observation", "Second observation"]}`

---

## Writing Quality Steps

**Good steps are:**
- **Actionable** - Clear what needs doing (`Run lint_backend on helpers/`)
- **Verifiable** - Can confirm completion (`All tests pass`, not "improve tests")
- **Atomic** - One logical outcome per step
- **Appropriately scoped** - Not too granular ("add import") or vague ("fix auth")

**Examples:**

| ❌ Bad | ✅ Good |
|--------|---------|
| Work on auth middleware | Implement SessionAuthMiddleware class in interfaces/api/middleware/ |
| Fix issues | Resolve mypy errors in persistence/models/library.py |
| Add imports | Create config_service module with ConfigService class |
| Test stuff | Verify lint_backend passes on nomarr/services |
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

Nested steps are rejected because they create ambiguous execution. If substeps are needed:
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

## Complete Example

If available, `plans/TASK-example-comprehensive.md` demonstrates all patterns.

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

---

## Schema Reference

The parser validates plans against this JSON schema. Each field's `description` explains the markdown syntax that produces it.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Task Plan",
  "description": "Schema for task plan markdown files. A plan is a static job card composed of ordered phases and flat step lists. Plans describe outcomes and constraints, not implementation procedures.",
  "type": "object",
  "required": ["title", "phases"],
  "properties": {
    "title": {
      "type": "string",
      "description": "Task title extracted from '# Task: <title>' or '# <title>' heading"
    },
    "Problem Statement": {
      "type": ["string", "array"],
      "description": "Content under '## Problem Statement'. Describes why the task exists, not how it will be executed."
    },
    "phases": {
      "type": "array",
      "minItems": 1,
      "description": "Ordered list of semantic work phases. Phases are numbered sequentially starting from 1.",
      "items": { "$ref": "#/definitions/phase" }
    },
    "Completion Criteria": {
      "type": ["string", "array"],
      "description": "Conditions that define when the task is complete. Must be outcome-based, not procedural."
    },
    "References": {
      "type": ["string", "array"],
      "description": "Optional references to related docs, issues, or prior plans."
    }
  },
  "additionalProperties": {
    "description": "Additional '## Section' headers become top-level properties."
  },
  "definitions": {
    "phase": {
      "type": "object",
      "required": ["number", "title", "steps"],
      "properties": {
        "number": {
          "type": "integer",
          "minimum": 1,
          "description": "Phase number extracted from '### Phase N:'. Must be sequential with no gaps."
        },
        "title": {
          "type": "string",
          "description": "Semantic phase title. Describes an outcome, not an action list."
        },
        "steps": {
          "type": "array",
          "description": "Flat list of checklist steps. Steps MUST NOT be nested.",
          "items": { "$ref": "#/definitions/step" }
        },
        "annotations": {
          "type": "object",
          "description": "Phase-level annotations. Any '**Marker:** text' after steps becomes { Marker: text }.",
          "additionalProperties": { "type": "string" }
        }
      }
    },
    "step": {
      "type": "object",
      "required": ["id", "text", "done"],
      "properties": {
        "id": {
          "type": "string",
          "description": "Auto-generated as 'P{phase}-S{index}'. Do not include manually."
        },
        "text": {
          "type": "string",
          "description": "Step description from '- [ ] <text>' or '- [x] <text>'."
        },
        "done": {
          "type": "boolean",
          "description": "True if checkbox is '[x]' or '[X]'."
        },
        "annotations": {
          "type": "object",
          "description": "Step-level annotations. Indented '**Marker:** text' under the step becomes { Marker: text }.",
          "additionalProperties": { "type": "string" }
        }
      }
    }
  }
}
```

