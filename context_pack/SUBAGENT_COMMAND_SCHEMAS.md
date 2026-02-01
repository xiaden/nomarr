# Subagent Command Schemas

Exact tool call shapes for Designer → QA → Main agent pipeline.
Designer outputs these; QA validates them; Main executes them verbatim.

---

## Edit Tools (Designer Allowlist)

These are the ONLY tools Designer can emit in `commands[]`.

### `atomic_replace`

Multiple string replacements in a single atomic write. All or nothing.

**Args Schema:**
```json
{
  "file_path": "string (workspace-relative path)",
  "replacements": [
    {
      "old_string": "string (exact text to find - must match exactly once)",
      "new_string": "string (replacement text)"
    }
  ]
}
```

**Validation Rules:**
- Each `old_string` must match exactly once (0 matches = error, 2+ = ambiguous)
- No overlapping replacement spans
- File must be valid UTF-8

**Success Response:**
```json
{
  "path": "nomarr/helpers/file_helpers.py",
  "changed": true,
  "replacements_applied": 2,
  "details": [
    {"old_string_preview": "def get_file(...", "status": "applied"}
  ]
}
```

**Failure Response:**
```json
{
  "path": "nomarr/helpers/file_helpers.py",
  "error": "Validation failed - no changes made",
  "validation_errors": ["Replacement 0: ambiguous (2 occurrences): def get..."],
  "changed": false
}
```

---

### `move_text`

Move lines within a file or across files. Atomic per file.

**Args Schema (same-file):**
```json
{
  "file_path": "string (workspace-relative path)",
  "source_start": "integer (1-indexed, inclusive)",
  "source_end": "integer (1-indexed, inclusive)",
  "target_line": "integer (insert BEFORE this line; use line_count+1 to append)"
}
```

**Args Schema (cross-file):**
```json
{
  "file_path": "string (source file path)",
  "source_start": "integer",
  "source_end": "integer",
  "target_line": "integer",
  "target_file": "string (destination file path - must exist)"
}
```

**Validation Rules:**
- `source_start` >= 1
- `source_end` >= `source_start`
- Both must be within file length
- `target_line` can be 1 to line_count+1
- For cross-file: target file must exist

**Success Response (same-file):**
```json
{
  "path": "nomarr/components/library/scanner.py",
  "changed": true,
  "lines_moved": 15,
  "source_range": {"start": 10, "end": 24},
  "target_line": 50
}
```

**Success Response (cross-file):**
```json
{
  "source_file": "nomarr/components/library/scanner.py",
  "target_file": "nomarr/components/library/batch_scanner.py",
  "changed": true,
  "lines_moved": 15,
  "source_range": {"start": 10, "end": 24},
  "target_line": 1
}
```

---

## Verification Tool

### `lint_backend`

Run ruff + mypy (+ import-linter when `check_all=true`).

**Args Schema:**
```json
{
  "path": "string | null (workspace-relative path to lint; default: 'nomarr/')",
  "check_all": "boolean (false = only modified/untracked files; true = all files + import-linter)"
}
```

**Clean Response:**
```json
{
  "ruff": {},
  "mypy": {},
  "summary": {"total_errors": 0, "clean": true, "files_checked": 5}
}
```

**Error Response:**
```json
{
  "ruff": {
    "E501": {
      "description": "Line too long",
      "fix_available": true,
      "occurrences": [{"file": "nomarr/helpers/x.py", "line": 42}]
    }
  },
  "mypy": {
    "arg-type": {
      "description": "Argument 1 has incompatible type",
      "fix_available": false,
      "occurrences": [{"file": "nomarr/helpers/x.py", "line": 55}]
    }
  },
  "summary": {"total_errors": 2, "clean": false, "files_checked": 5}
}
```

---

## Designer Output Schema

Designer MUST return exactly this JSON structure (no markdown, no prose):

```json
{
  "touched_files": ["path/to/file1.py", "path/to/file2.py"],
  "commands": [
    {
      "tool": "atomic_replace | move_text",
      "args": { /* exact args per tool schema above */ },
      "reason": "string (1 sentence max)"
    }
  ],
  "changed_signatures": [
    "file_helpers.get_file() now returns Tuple[File, str]"
  ],
  "verification": {
    "tool": "lint_backend",
    "args": {"path": "nomarr/helpers", "check_all": false}
  }
}
```

**Rules:**
- `touched_files`: All files that will be modified
- `commands`: Ordered list; each `tool` must be in allowlist; `args` must match schema exactly
- `changed_signatures`: Public API changes; empty array `[]` if none
- `verification`: Required; specifies exact lint invocation

**On Error (cannot produce valid commands):**
```json
{
  "touched_files": [],
  "commands": [{"tool": "__error__", "args": {}, "reason": "Could not locate symbol X in file Y"}],
  "changed_signatures": [],
  "verification": {"tool": "lint_backend", "args": {"path": "", "check_all": false}}
}
```

---

## QA Output Schema

QA MUST return exactly this JSON structure:

**APPROVED:**
```json
{
  "decision": "APPROVED",
  "commands": [ /* same as Designer, may be modified */ ],
  "verification": { /* same as Designer, may be widened */ },
  "reasons": ["optional notes"],
  "spot_checks": [
    "verified: symbol 'get_file' exists in helpers.py",
    "not checked: semantic correctness of replacement"
  ]
}
```

**REJECTED:**
```json
{
  "decision": "REJECTED",
  "commands": [],
  "verification": null,
  "reasons": [
    "Replacement 0 touches file outside step scope",
    "move_text args missing target_file for cross-file move"
  ],
  "required_changes": [
    "Remove command targeting nomarr/services/",
    "Add target_file to move_text command"
  ],
  "spot_checks": ["verified: step scope is nomarr/helpers only"]
}
```

**Rules:**
- `decision`: Exactly `"APPROVED"` or `"REJECTED"`
- `commands`: Required for APPROVED (can be modified from Designer); empty for REJECTED
- `verification`: Required for APPROVED; null for REJECTED
- `reasons`: Required for REJECTED; optional for APPROVED
- `required_changes`: Required for REJECTED
- `spot_checks`: Optional; documents what QA verified or skipped

---

## Validation Failure Modes

| Check | Owner | Result |
|-------|-------|--------|
| Designer JSON invalid | Code validator | BLOCKED, log parse error |
| Designer unknown tool | Code validator | BLOCKED, "unknown tool: X" |
| Designer args don't match schema | Code validator | BLOCKED, "invalid args for tool X" |
| QA JSON invalid | Code validator | BLOCKED, log parse error |
| QA decision not APPROVED/REJECTED | Code validator | BLOCKED, "invalid decision" |
| QA returns REJECTED | Main agent | BLOCKED, log QA reasons, no retry |
| Tool execution fails | Main agent | FAILED, log tool error |
| Lint fails after apply | Main agent | FAILED, log lint summary |

---

## Read-Only Tools (QA Spot-Check Allowlist)

QA may use these for verification only:

| Tool | Purpose |
|------|---------|
| `locate_symbol` | Verify symbol exists |
| `get_source` | Verify signature matches claim |
| `discover_api` | Verify module shape |

QA should NOT use: `trace_calls`, `trace_endpoint`, `read_file` (these are research, not verification).

---

## Work Order Fields (Main → Subagents)

Main agent provides this context to subagents:

```json
{
  "step_id": "phase-2.step-3",
  "step_text": "Split analytics_comp.py into 5 one-export files...",
  "scope_allowlist": ["nomarr/components/analytics/"],
  "invariants": [
    "no import shape changes",
    "no _id/_key renames",
    "no behavior changes"
  ],
  "acceptance": {
    "lint": {"path": "nomarr/components/analytics", "check_all": false},
    "phase_boundary_lint": {"path": "nomarr/", "check_all": true}
  }
}
```

Designer and QA validate against `scope_allowlist` and `invariants`.
