# ASR Format Overhaul — Design Document

**Status:** Completed  
**Author:** Agent  
**Created:** 2026-04-09  

---

## Scope

Redesign the ASR (Architecturally Significant Requirements) subsystem of the code-intel MCP server. Scope covers: full rewrite of `asr_md.py` helper, three tool files (`asr_create.py`, `asr_read.py`, `asr_search.py`), three `server.py` wrapper registrations, and updating three locations in `copilot-instructions.md`. The nomarr application, frontend, and all other code-intel tools are unaffected. Writing new test coverage for the ASR tools is in scope (no tests currently exist for any ASR tool). Updating one agent definition file (`.github/agents/Support/support-librarian.agent.md`) to remove references to the removed `quality_attribute` parameter and `linked_adrs` field is also in scope.

The 16 existing ASR files in `artifacts/requirements/` use the old format and are treated as garbage data — they are kept as-is and serve as parser test fixtures. They are not renamed or content-migrated as part of this work. The new tools must handle them gracefully: silently skip on search, return a structured error on direct read.

---

## Problem Statement

The existing ASR format was designed to mirror ISO/IEEE quality attribute scenario templates (stimulus, response measure, quality attribute label). In practice this format is over-specified and fragile: agents produce incorrect stimulus/response_measure splits, string priority labels ("High", "Critical") cannot be compared or sorted, the slug-based filename makes renaming or renumbering files unnecessarily disruptive, and the large number of required fields (title, quality_attribute, stimulus, response_measure, constraints, linked_adrs, source) creates friction that causes agents to under-document requirements. The result is 16 files that are technically valid but structurally inconsistent and hard to query by importance. The new format collapses the schema to two required fields (priority integer + requirement text), removes all metadata fields that don't carry query value, and standardises filenames to a clean `ASR-NNNN.md` pattern with no slugs.

---

## Architecture

## 1. New ASR Markdown Schema

### File naming

`ASR-{NNNN}.md` — zero-padded 4-digit number. Example: `ASR-0001.md`, `ASR-0016.md`.
Numbers auto-increment from the maximum existing file number. Numbers are never re-used or recycled.

### Format

```
# ASR-NNNN

**Priority:** N
**Status:** Active
**Created:** YYYY-MM-DD
**Updated:** YYYY-MM-DD

## Requirement

[Full requirement statement]

## Notes

[Optional. ADR references and background only.]
```

The `## Notes` section is omitted entirely from generated files when `notes` is empty.

### Field rules

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| H1 title | `# ASR-{N:04d}` — no text after the ID | Yes | Must match `r"^#\s+ASR-(\d+)\s*$"` |
| Priority | Non-negative integer | Yes | `>= 0`; lower value = higher importance; gaps allowed |
| Status | String | Yes | `"Active"`, `"Archived"`, or `r"^Superseded by ASR-\d{4}$"` |
| Created | ISO date `YYYY-MM-DD` | Yes | Set at creation; never changed by `asr_create` logic |
| Updated | ISO date `YYYY-MM-DD` | Yes | Set at creation; updated on any future edit |
| `## Requirement` | String | Yes | Non-empty body text; scoped and measurable |
| `## Notes` | String | No | When present: ADR references and background only |

### Removed fields (compared to current format)

title (descriptive slug in H1), `quality_attribute`, `stimulus`, `response_measure`, `constraints`, `linked_adrs`, `source`, `date` (split into `created`/`updated`).

---

## 2. `asr_md.py` — Full Rewrite

File: `code-intel/src/mcp_code_intel/helpers/asr_md.py`

The entire file is replaced. Key elements:

### Module-level constants

```python
ASR_STATUSES_EXACT: frozenset[str] = frozenset({"Active", "Archived"})
SUPERSEDED_PATTERN: re.Pattern[str] = re.compile(r"^Superseded by ASR-\d{4}$")
REQUIREMENTS_DIR = "artifacts/requirements"
ASR_PREFIX = "ASR-"
```

Remove: `ASR_STATUSES` (old set), `ASR_PRIORITIES`.

### Regex patterns

```python
TITLE_PATTERN: re.Pattern[str] = re.compile(r"^#\s+ASR-(\d+)\s*$")
META_PATTERN: re.Pattern[str] = re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")
SECTION_PATTERN: re.Pattern[str] = re.compile(r"^##\s+(.+)$")
```

Note: `TITLE_PATTERN` no longer captures a title string — only the number. The `$` anchors white-space-only suffix.

### `ASR` dataclass

```python
@dataclass
class ASR:
    number: int
    priority: int
    status: str
    created: str
    updated: str
    requirement: str
    notes: str = ""
```

Remove fields: `title`, `date`, `quality_attribute`, `priority` (was `str`), `source`, `linked_adrs`, `sections` (was `dict`).

### Validation functions

Replace all existing validation with:

```python
def validate_status(status: str) -> str | None:
    if status in ASR_STATUSES_EXACT:
        return None
    if SUPERSEDED_PATTERN.match(status):
        return None
    return (
        f"Invalid status {status!r}: must be 'Active', 'Archived', "
        "or 'Superseded by ASR-NNNN'"
    )

def validate_priority(priority: int) -> str | None:
    if not isinstance(priority, int) or isinstance(priority, bool) or priority < 0:
        return f"Invalid priority {priority!r}: must be a non-negative integer"
    return None
```

Remove: `validate_quality_attribute`.

### `generate_asr`

```python
def generate_asr(asr: ASR) -> str:
    lines: list[str] = []
    lines.append(f"# ASR-{asr.number:04d}")
    lines.append("")
    lines.append(f"**Priority:** {asr.priority}")
    lines.append(f"**Status:** {asr.status}")
    lines.append(f"**Created:** {asr.created}")
    lines.append(f"**Updated:** {asr.updated}")
    lines.append("")
    lines.append("## Requirement")
    lines.append("")
    lines.append(asr.requirement.strip())
    lines.append("")
    if asr.notes.strip():
        lines.append("## Notes")
        lines.append("")
        lines.append(asr.notes.strip())
        lines.append("")
    return "\n".join(lines)
```

### `make_asr_filename`

```python
def make_asr_filename(number: int) -> str:
    return f"ASR-{number:04d}.md"
```

Remove the `title` parameter. Remove `_slugify` helper entirely (no longer needed anywhere).

### `next_asr_number`

```python
def next_asr_number(requirements_dir: Path) -> int:
    if not requirements_dir.exists():
        return 1
    existing = list(requirements_dir.glob("ASR-*.md"))
    if not existing:
        return 1
    numbers: list[int] = []
    for f in existing:
        m = re.match(r"^ASR-(\d+)\.md$", f.name)
        if m:
            numbers.append(int(m.group(1)))
    return max(numbers, default=0) + 1
```

The regex `r"^ASR-(\d+)\.md$"` only matches new-style filenames (no slug). Old-style files (`ASR-001-slug.md`) include a slug after the number and will not match — they are naturally excluded without any migration step. New file numbering starts from 1 regardless of old files.

### `parse_asr`

State machine with three states: `header`, `requirement`, `notes`.

```python
def parse_asr(markdown: str) -> ASR:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    number = 0
    priority_raw: str | None = None
    status = ""
    created = ""
    updated = ""

    state = "header"
    requirement_lines: list[str] = []
    notes_lines: list[str] = []

    for line in lines:
        if state == "header":
            m = TITLE_PATTERN.match(line)
            if m:
                number = int(m.group(1))
                continue
            m = META_PATTERN.match(line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                if key == "Priority":
                    priority_raw = val
                elif key == "Status":
                    status = val
                elif key == "Created":
                    created = val
                elif key == "Updated":
                    updated = val
                continue
            m = SECTION_PATTERN.match(line)
            if m:
                section_name = m.group(1).strip()
                if section_name == "Requirement":
                    state = "requirement"
                elif section_name == "Notes":
                    state = "notes"
        elif state == "requirement":
            m = SECTION_PATTERN.match(line)
            if m and m.group(1).strip() == "Notes":
                state = "notes"
            else:
                requirement_lines.append(line)
        elif state == "notes":
            notes_lines.append(line)

    requirement = "\n".join(requirement_lines).strip()
    notes = "\n".join(notes_lines).strip()

    if number == 0:
        raise ValueError("ASR number not found in markdown")
    if not requirement:
        raise ValueError("Requirement section not found or empty")

Note: `parse_asr` raises `ValueError` on any malformed file. Callers (`asr_read`, `asr_search`) are responsible for catching these errors and handling them gracefully — see Sections 4 and 5.

    priority = 0
    if priority_raw is not None:
        try:
            priority = int(priority_raw)
        except ValueError:
            raise ValueError(f"Invalid priority value: {priority_raw!r}")

    return ASR(
        number=number,
        priority=priority,
        status=status or "Active",
        created=created,
        updated=updated,
        requirement=requirement,
        notes=notes,
    )
```

### `parse_asr_metadata`

Fast header-only parse for `asr_search` when no body query is needed:

```python
def parse_asr_metadata(markdown: str) -> dict[str, Any]:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    result: dict[str, Any] = {
        "number": 0,
        "priority": 0,
        "status": "",
        "created": "",
        "updated": "",
    }

    for line in lines:
        if line.startswith("## "):
            break
        m = TITLE_PATTERN.match(line)
        if m:
            result["number"] = int(m.group(1))
            continue
        m = META_PATTERN.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key == "Priority":
                try:
                    result["priority"] = int(val)
                except ValueError:
                    pass
            elif key == "Status":
                result["status"] = val
            elif key == "Created":
                result["created"] = val
            elif key == "Updated":
                result["updated"] = val

    return result
```

Note: `priority` is parsed as `int`, not `str`. Remove old `quality_attribute` and `date` keys.

### `today_iso` — unchanged

Keep as-is: `return date.today().isoformat()`.

### `_unescape_literal_newlines` — keep

Retained for use in `asr_create` (requirement and notes text arrive via MCP transport with literal `\n` sequences).

---

## 3. `asr_create.py` — Full Rewrite

File: `code-intel/src/mcp_code_intel/tools/asr_create.py`

### New signature

```python
def asr_create(
    priority: int,
    requirement: str,
    notes: str = "",
    status: str = "Active",
    *,
    workspace_root: Path,
) -> dict[str, Any]:
```

### Validation and logic

1. `validate_priority(priority)` — reject if not non-negative int
2. Strip and check `requirement` is non-empty; return `{"error": "invalid_requirement", ...}` if blank
3. `validate_status(status)` — reject invalid statuses
4. Unescape: `requirement = _unescape_literal_newlines(requirement)`, same for `notes`
5. `requirements_dir = workspace_root / REQUIREMENTS_DIR`; `requirements_dir.mkdir(parents=True, exist_ok=True)`
6. `number = next_asr_number(requirements_dir)`
7. `filename = make_asr_filename(number)`; check not already exists
8. Build `ASR(number=number, priority=priority, status=status, created=today_iso(), updated=today_iso(), requirement=requirement.strip(), notes=notes.strip())`
9. `markdown = generate_asr(asr)`
10. Write file; return `{"path": rel_path, "number": number, "markdown": markdown}`

### Removed imports

Remove: `validate_quality_attribute`, `make_asr_filename` old call (now takes one arg), all old parameter names from function body.

### Return schema

Success: `{"path": "artifacts/requirements/ASR-NNNN.md", "number": N, "markdown": "..."}`
Error: `{"error": "...", "message": "..."}`

---

## 4. `asr_read.py` — Targeted Updates

File: `code-intel/src/mcp_code_intel/tools/asr_read.py`

### `_resolve_asr_path` — rewrite

New resolver supports only numeric identifiers (no slug):

```python
def _resolve_asr_path(name: str, workspace_root: Path) -> Path | None:
    requirements_dir = workspace_root / REQUIREMENTS_DIR
    if not requirements_dir.exists():
        return None

    # Strip .md suffix
    if name.endswith(".md"):
        name = name[:-3]

    # Strip optional ASR- prefix, then require pure digits
    stripped = name.removeprefix(ASR_PREFIX)
    if stripped.isdigit():
        num = int(stripped)
        candidate = requirements_dir / f"ASR-{num:04d}.md"
        if candidate.exists():
            return candidate

    return None
```

Accepted forms: `"1"`, `"0001"`, `"ASR-0001"`, `"ASR-0001.md"`. Slug-format names (`"ASR-001-fast-search"`) are no longer resolved — they fail to strip to pure digits.

### Error handling for malformed files

Wrap the `parse_asr` call in a try/except block:

```python
try:
    asr = parse_asr(content)
except ValueError as e:
    return {"error": "parse_error", "message": str(e), "path": rel_path}
```

This allows `asr_read` to be called on old-format files and return a structured error rather than crashing. The `path` field is always included so the caller can inspect the file directly.

### Return schema — update

```python
return {
    "number": asr.number,
    "priority": asr.priority,
    "status": asr.status,
    "created": asr.created,
    "updated": asr.updated,
    "requirement": asr.requirement,
    "notes": asr.notes,
    "path": rel_path,
}
```

Remove old keys: `title`, `date`, `quality_attribute`, `source`, `linked_adrs`, `sections`.

---

## 5. `asr_search.py` — Full Rewrite

File: `code-intel/src/mcp_code_intel/tools/asr_search.py`

### New signature

```python
def asr_search(
    query: str = "",
    status: str = "",
    priority_min: int | None = None,
    priority_max: int | None = None,
    limit: int = 50,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
```

### Filter logic

For each ASR file:
1. `status`: skip if `meta["status"] != status` (exact match, non-empty filter only)
2. `priority_min`: skip if `meta["priority"] < priority_min`
3. `priority_max`: skip if `meta["priority"] > priority_max`
4. `query`: skip if `query_lower` not in `(requirement + " " + notes).lower()` — requires full parse

Use fast path (`parse_asr_metadata`) when no `query` filter; use full parse (`parse_asr`) when `query` is set.

In both cases, wrap the parse call in a try/except and **skip the file silently** if it raises `ValueError`. This prevents old-format or malformed files from crashing search:

```python
try:
    meta = parse_asr_metadata(content)  # or parse_asr(content) when query set
except ValueError:
    continue  # skip malformed / old-format files silently
```

### Sort order

```python
results.sort(key=lambda r: r["priority"])  # ascending: 0 first
```

### Result item schema

```python
{
    "number": int,
    "priority": int,
    "status": str,
    "created": str,
    "updated": str,
    "path": str,
}
```

Requirement text is intentionally excluded from results to keep output compact. The `path` field enables callers to read the full content with `asr_read`.

### Limit handling

`effective_limit = min(limit, _MAX_LIMIT) if limit > 0 else _MAX_LIMIT` — same pattern as current code.

### Return schema

`{"results": [...], "total": N}` — same shape as current code.

---

## 6. `server.py` Wrapper Updates

File: `code-intel/src/mcp_code_intel/server.py`

Three wrapper functions need updating (approximately lines 1186–1317 in current file).

### `asr_create` wrapper

Replace all `Annotated` parameters and update the docstring:

```python
@mcp.tool()
def asr_create(
    priority: Annotated[
        int,
        "Priority integer — non-negative; lower = higher importance. "
        "0 is most critical. Use multiples of 100 for new ASRs to allow insertions.",
    ],
    requirement: Annotated[
        str,
        "The requirement body — scoped, measurable, technology-independent, "
        "no implementation detail",
    ],
    notes: Annotated[
        str,
        "Optional notes — ADR references and background context only. "
        "No implementation detail. No tech names. (optional)",
    ] = "",
    status: Annotated[
        str,
        "Status: 'Active', 'Archived', or 'Superseded by ASR-NNNN'",
    ] = "Active",
) -> CallToolResult:
    """Create a new Architecturally Significant Requirement (ASR) in artifacts/requirements/.

    ASRs document the requirements that motivate architectural decisions.
    They are the 'why' behind ADRs.
    """
    result = asr_create_impl(
        priority=priority,
        requirement=requirement,
        notes=notes,
        status=status,
        workspace_root=ROOT,
    )
    ...
```

Remove all old keyword args from the `asr_create_impl(...)` call.

### `asr_read` wrapper

Update only the `name` parameter description:

```python
name: Annotated[
    str,
    "ASR identifier — number ('1', '0001'), "
    "or ASR-prefixed ('ASR-0001', 'ASR-0001.md')",
],
```

Update docstring to remove reference to slugs.

### `asr_search` wrapper

Replace `quality_attribute` and `priority` parameters with `priority_min` and `priority_max`:

```python
@mcp.tool()
def asr_search(
    query: Annotated[
        str,
        "Text to search in requirement and notes, case-insensitive (optional)",
    ] = "",
    status: Annotated[str, "Filter by exact status match (optional)"] = "",
    priority_min: Annotated[
        int | None,
        "Include only ASRs with priority >= this value (optional)",
    ] = None,
    priority_max: Annotated[
        int | None,
        "Include only ASRs with priority <= this value (optional)",
    ] = None,
    limit: Annotated[int, "Maximum results to return (capped at 50)"] = 50,
) -> CallToolResult:
    """Search Architecturally Significant Requirements by status, priority range, and/or text query.

    Returns results sorted by priority ascending (lowest number = highest priority first).
    """
    result = asr_search_impl(
        query=query,
        status=status,
        priority_min=priority_min,
        priority_max=priority_max,
        limit=limit,
        workspace_root=ROOT,
    )
    ...
```

---

## 7. Existing Files — No Migration

The 16 existing files in `artifacts/requirements/` use the old format (`ASR-NNN-slug.md` with old schema fields). They are **not renamed or rewritten** as part of this work. They are kept as-is and treated as garbage data / parser test fixtures.

The new tools coexist with them safely:
- `asr_search` skips all files that fail to parse (old format files will fail the `TITLE_PATTERN` match and raise, triggering the skip)
- `asr_read` returns a structured error dict for any file that fails to parse
- `next_asr_number` only matches `ASR-NNNN.md` (4-digit, no slug) — old files are naturally excluded, so new files start at `ASR-0001.md` without collision

Future editorial rewriting of old ASR content into the new format is a separate, out-of-scope concern.

---

## 8. `copilot-instructions.md` Updates

File: `d:\\Github\\nomarr\\.github\\copilot-instructions.md`

Three locations need updating:

**Location 1 — Line 87** (artifact chain description):

Current: `"with linked_adrs on the ASR closing the loop."`
Replace with: `"ASRs are standalone — no explicit link field; reference ADRs by number in the Notes section if relevant."`

**Location 2 — Lines 106–120** (When to Create ASRs section):

The `linked_adrs` guidance block must be removed. The "quality attribute goals" language should be simplified. The updated section should read:

```
### When to Create ASRs (`asr_create`)

ASRs capture the requirements that motivate architectural decisions. They are the 'why' behind ADRs.

`asr_create` writes directly to `artifacts/requirements/` (no approval workflow needed).

Create an ASR when:
- **A stakeholder expresses a non-functional or architectural requirement** — record it before design begins
- **A constraint limits design options** — e.g., "Must not require GPU at runtime"
- **A measurable quality goal shapes the architecture** — e.g., "Search must complete in < 500ms at production scale"
- **An operational requirement drives deployment decisions** — e.g., "System must recover automatically after DB restart within 30s"

Use `priority` (integer) to rank importance: 0 = most critical, increment by 100 for new entries to allow future insertions between existing priorities.

**Threshold:** If a requirement will constrain the architecture or exclude design options — it's an ASR.
```

**Location 3 — Line 151** (Before acting, check table):

Current: `` `asr_search(quality_attribute="*attr*")` ``
Replace with: `` `asr_search(query="*topic*")` ``

---

## 9. Test Coverage

No tests currently exist for any ASR tool (`test_asr_md.py`, `test_asr_tools.py` are absent from `code-intel/tests/`). New tests must be written as part of this overhaul:

- `test_asr_md.py` — unit tests for `generate_asr`, `parse_asr`, `parse_asr_metadata`, `validate_status`, `validate_priority`, `make_asr_filename`, `next_asr_number`
- `test_asr_tools.py` — integration tests for `asr_create`, `asr_read`, `asr_search` using a temp directory fixture (follow pattern in `test_adr_tools.py` or `test_dd_tools.py`)

Test cases must cover: round-trip generate→parse, parse error on missing Requirement section, priority min/max filtering, status filter, query text search, sort order (priority ascending), name resolution variants for `asr_read`, and the `notes` field being optional.

---

## 10. Agent Definition Updates

File: `.github/agents/Support/support-librarian.agent.md`

This agent definition describes how to use ASR tools and references two contracts that are being removed. Both references must be updated alongside the tool changes.

### Change 1 — Remove `quality_attribute` parameter from ASR Search guidance

**Section: "1. ASR Search"**

Current bullet to remove:
```
- `asr_search(quality_attribute="{attr}")` — by quality attribute (performance, security, etc.)
```

Remove this bullet entirely. The `quality_attribute` parameter does not exist in the new `asr_search` signature. Replace it with:
```
- `asr_search(priority_min=N, priority_max=N)` — by priority range (optional)
```

### Change 2 — Remove `linked_adrs` from Cross-Reference guidance

**Section: "5. Cross-Reference"**

Current bullet to remove:
```
- ASRs list `linked_adrs` that satisfy them
```

Remove this bullet entirely. ASRs no longer carry a `linked_adrs` field. ADR references belong in the `## Notes` section of the ASR body as free text, not as a structured field.

---

## Design Goals

1. **Minimal schema**: Two required fields (priority integer + requirement text) — no more than needed to express importance and intent
2. **Sortable priority**: Integer priority enables direct comparison and ascending sort; string labels cannot be sorted
3. **Clean filenames**: `ASR-NNNN.md` with no slug — survives requirement text changes without renaming
4. **Full round-trip fidelity**: `parse_asr(generate_asr(asr)) == asr` for all valid inputs
5. **Fast search path**: `parse_asr_metadata` avoids reading body when only metadata filters are applied
6. **Zero breaking changes to other tools**: All changes are inside the ASR subsystem; no other MCP tools or nomarr application code are touched

---

## Constraints

- No `asr_update` tool — YAGNI. Content updates are out of scope for this overhaul. File edits are manual for now.
- Content evaluation and rewriting of the 16 existing ASR files is out of scope for this DD. They are kept as-is.
- The new parser (`parse_asr`) is strict — it raises `ValueError` on malformed input. Fault tolerance lives in the tools: `asr_search` skips malformed files silently, `asr_read` returns a structured error dict.
- No changes to MCP protocol or tool registry infrastructure — only parameter signatures and implementations change.
- `_unescape_literal_newlines` must be retained: multi-line requirement text arrives via MCP transport with literal `\n` escape sequences.

---

## Open Questions

1. **`asr_search` result inclusion of requirement text**: The current design omits requirement text from search results to keep responses compact. Is this the right call, or should a truncated snippet be included? Decision deferred — can be added later without breaking callers.

---

## Layer Map

All changes are within `code-intel/src/mcp_code_intel/`:

| File | Change type | Layer |
|------|-------------|-------|
| `helpers/asr_md.py` | Full rewrite | Helper |
| `tools/asr_create.py` | Full rewrite | Tool |
| `tools/asr_read.py` | Resolver + return schema update | Tool |
| `tools/asr_search.py` | Full rewrite | Tool |
| `server.py` | Wrapper parameter updates (3 functions) | Server |
| `code-intel/tests/test_asr_md.py` | New file | Tests |
| `code-intel/tests/test_asr_tools.py` | New file | Tests |
| `.github/copilot-instructions.md` | 3 targeted string replacements | Docs |
| `.github/agents/Support/support-librarian.agent.md` | 2 targeted removals (quality_attribute bullet, linked_adrs bullet) | Docs |

Dependency direction: `asr_md.py` (helper) ← `asr_create/read/search.py` (tools) ← `server.py`. No upward imports.

---
