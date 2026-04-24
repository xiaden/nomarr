# ASR Format Overhaul — Implementation Parts

**Design doc:** [`DD-asr-format-overhaul.md`](../../pending/DD-asr-format-overhaul.md)
**Created:** 2026-04-09
**Status:** Plans created, not yet executed

---

## Parts

 | Part | Title | Depends On | Scope |
 | ------ | ------- | ------------ | --------- |
 | A | Helper Rewrite | None | Full rewrite of `asr_md.py` |
 | B | Tool Rewrites | A | `asr_create.py`, `asr_read.py`, `asr_search.py` |
 | C | Server + Instructions | B | `server.py` wrappers, `copilot-instructions.md`, `support-librarian.agent.md` |
 | D | Tests | A, B | `test_asr_md.py`, `test_asr_tools.py` |

---

## Dependency Graph

```
A → B → C
    ↓
    D
```

---

## Execution Rounds

 | Round | Parts | Notes |
 | ------- | ------- | ------- |
 | 1 | A | Foundation — helper rewrite |
 | 2 | B | Tool rewrites depend on A |
 | 3 | C, D | C depends on B; D depends on A+B; run in parallel |

---

## Per-Part Scope

### Part A: Helper Rewrite

**Files:** `code-intel/src/mcp_code_intel/helpers/asr_md.py`

Key changes:

- Replace `ASR` dataclass: remove `title`, `date`, `quality_attribute`, `source`, `linked_adrs`, `sections`; add `created`, `updated`, `requirement`, `notes: str = ""`; change `priority` from `str` to `int`
- Replace `TITLE_PATTERN`: number-only capture `r"^#\s+ASR-(\d+)\s*$"` — no title string
- Replace constants: add `ASR_STATUSES_EXACT`, `SUPERSEDED_PATTERN`; remove `ASR_STATUSES` and `ASR_PRIORITIES`
- Replace `validate_status` and `validate_priority`; remove `validate_quality_attribute`
- Replace `generate_asr`: H1 is `# ASR-NNNN`, body is `## Requirement` + optional `## Notes`
- Replace `make_asr_filename`: no `title` parameter
- Replace `next_asr_number`: new regex excludes old slug files
- Replace `parse_asr`: 3-state machine (header / requirement / notes)
- Replace `parse_asr_metadata`: returns `priority` as `int`; drops old keys
- Remove `_slugify`; keep `_unescape_literal_newlines` and `today_iso` unchanged

### Part B: Tool Rewrites

**Files:**

- `code-intel/src/mcp_code_intel/tools/asr_create.py`
- `code-intel/src/mcp_code_intel/tools/asr_read.py`
- `code-intel/src/mcp_code_intel/tools/asr_search.py`

Key changes:

- `asr_create`: new signature `(priority: int, requirement: str, notes: str = "", status: str = "Active", *, workspace_root: Path)`; remove all ISO/IEEE fields
- `asr_read`: simplified `_resolve_asr_path` (pure digits → `ASR-{num:04d}.md`, no glob); `parse_asr` wrapped in `try/except ValueError`; updated return dict
- `asr_search`: new signature with `priority_min`/`priority_max` instead of `quality_attribute`/`priority`; numeric priority filtering; fast/full parse selection; sort ascending by priority; updated result schema

### Part C: Server + Instructions

**Files:**

- `code-intel/src/mcp_code_intel/server.py` (3 wrapper functions)
- `.github/copilot-instructions.md` (3 targeted replacements)
- `.github/agents/Support/support-librarian.agent.md` (2 targeted removals)

Key changes:

- `asr_create` wrapper: replace all old `Annotated` params with `priority`, `requirement`, `notes`, `status`
- `asr_read` wrapper: update `name` parameter description to remove slug reference
- `asr_search` wrapper: replace `quality_attribute`/`priority` params with `priority_min`/`priority_max`
- `copilot-instructions.md`: update ASR chain description, When to Create ASRs section, and table row referencing `quality_attribute`
- `support-librarian.agent.md`: remove `quality_attribute` bullet; add `priority_min`/`priority_max` bullet; remove `linked_adrs` bullet

### Part D: Tests

**Files created:**

- `code-intel/tests/test_asr_md.py`
- `code-intel/tests/test_asr_tools.py`

Key coverage:

- `test_asr_md.py`: `generate_asr` (with/without notes), `parse_asr` round-trip, parse errors (missing number, missing Requirement), `parse_asr_metadata` int priority, `validate_status`, `validate_priority`, `make_asr_filename`, `next_asr_number` (empty dir, existing files, old-format exclusion)
- `test_asr_tools.py`: `asr_create` (happy path, auto-numbering, validation errors, notes optional), `asr_read` (name resolution forms, not found, `parse_error` on old-format file), `asr_search` (no filter, status filter, priority range filter, query text filter, silently skips malformed files)
