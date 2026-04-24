# ASR Format Overhaul — Contracts Ledger

**Design doc:** `artifacts/designs/pending/DD-asr-format-overhaul.md`
**Last updated:** 2026-04-09 (Initial — no plans executed yet)

---

## Architectural Rules

### Code-Intel Layer

- Helper layer: `helpers/asr_md.py` — pure parsing/serialization, no I/O except `next_asr_number` (scans filesystem)
- Tool layer: `tools/asr_*.py` — filesystem I/O, call helpers
- Server layer: `server.py` — MCP wrappers, call tools

### Function Contracts

- All tools receive `workspace_root: Path` as keyword argument
- All tools return `dict[str, Any]`
- Tools handle errors by returning structured error dicts, not raising exceptions
- Helper functions are pure (no side effects, no I/O) except `next_asr_number`
- `parse_asr` and `parse_asr_metadata` raise `ValueError` on malformed input — callers catch and handle

---

## ASR Data Model

```python
@dataclass
class ASR:
    number: int       # ASR number (e.g., 1 for ASR-0001)
    priority: int     # Non-negative integer; lower = higher importance
    status: str       # "Active", "Archived", or "Superseded by ASR-NNNN"
    created: str      # ISO date YYYY-MM-DD; set at creation, never changed
    updated: str      # ISO date YYYY-MM-DD; updated on any edit
    requirement: str  # Non-empty requirement text
    notes: str = ""   # Optional notes; ADR references and background only
```

---

## Methods — `helpers/asr_md.py`

### Constants

 | Name | Value / Type | Notes |
 | ------ | ------------- | ------- |
 | `ASR_STATUSES_EXACT` | `frozenset({"Active", "Archived"})` | Exact-match statuses |
 | `SUPERSEDED_PATTERN` | `re.compile(r"^Superseded by ASR-\d{4}$")` | Pattern for superseded status |
 | `REQUIREMENTS_DIR` | `"artifacts/requirements"` | Unchanged from current |
 | `ASR_PREFIX` | `"ASR-"` | Unchanged from current |
 | `TITLE_PATTERN` | `re.compile(r"^#\s+ASR-(\d+)\s*$")` | Number-only capture; no title |
 | `META_PATTERN` | `re.compile(r"^\*\*(\w[\w\s]*):\*\*\s*(.*)$")` | Unchanged |
 | `SECTION_PATTERN` | `re.compile(r"^##\s+(.+)$")` | Unchanged |

### Functions

 | Function | Signature | Notes |
 | ---------- | ----------- | ------- |
 | `validate_status` | `(status: str) -> str \ | None` | Returns error message or `None` if valid |
 | `validate_priority` | `(priority: int) -> str \ | None` | Returns error message or `None`; rejects `bool`, negative |
 | `generate_asr` | `(asr: ASR) -> str` | Pure; omits `## Notes` section when `notes` is empty |
 | `make_asr_filename` | `(number: int) -> str` | Returns `"ASR-{number:04d}.md"` — no title arg |
 | `next_asr_number` | `(requirements_dir: Path) -> int` | Regex `r"^ASR-(\d+)\.md$"` — excludes old slug files |
 | `parse_asr` | `(markdown: str) -> ASR` | Raises `ValueError` on malformed input; 3-state machine |
 | `parse_asr_metadata` | `(markdown: str) -> dict[str, Any]` | Fast header-only parse; `priority` returned as `int` |
 | `today_iso` | `() -> str` | Unchanged from current |
 | `_unescape_literal_newlines` | `(text: str) -> str` | Unchanged from current |

**Removed:** `validate_quality_attribute`, `_slugify`

---

## API Contracts

### `asr_create`

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

Success: `{"path": "artifacts/requirements/ASR-NNNN.md", "number": N, "markdown": "..."}`

Errors:

- `{"error": "invalid_priority", "message": "..."}` — priority < 0, not int, or is bool
- `{"error": "invalid_requirement", "message": "Requirement cannot be empty"}` — blank requirement
- `{"error": "invalid_status", "message": "..."}` — unrecognised status string

### `asr_read`

```python
def asr_read(
    name: str,
    *,
    workspace_root: Path,
) -> dict[str, Any]:
```

Accepted `name` forms: `"1"`, `"0001"`, `"ASR-0001"`, `"ASR-0001.md"`
Rejected: slug-format names (`"ASR-001-fast-search"`) — return `asr_not_found`

Success:

```python
{
    "number": int,
    "priority": int,
    "status": str,
    "created": str,
    "updated": str,
    "requirement": str,
    "notes": str,
    "path": str,
}
```

Errors:

- `{"error": "invalid_name", "message": "..."}` — empty or contains path separators
- `{"error": "asr_not_found", "message": "...", "searched": str}` — file not found
- `{"error": "parse_error", "message": str, "path": str}` — malformed file (old-format included); `path` always present

### `asr_search`

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

Returns: `{"results": [...], "total": N}` — sorted by priority **ascending** (0 first)

Result item schema:

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

Filter behaviour:

- `status`: exact match, applied when non-empty
- `priority_min`: skip if `meta["priority"] < priority_min`
- `priority_max`: skip if `meta["priority"] > priority_max`
- `query`: case-insensitive substring match in `(requirement + " " + notes).lower()`; triggers full parse
- Fast path: `parse_asr_metadata` when no `query`; full parse `parse_asr` when `query` is set
- Malformed / old-format files: silently skipped (`ValueError` caught, file skipped with `continue`)

---

## Decisions

 | # | Decision | Rationale |
 | --- | ---------- | ----------- |
 | 1 | Old-format ASRs not migrated | DD constraint — coexistence strategy; old files are garbage data / parser test fixtures |
 | 2 | `parse_asr` raises `ValueError` on malformed input | Fault tolerance belongs in callers: `asr_search` skips silently, `asr_read` returns structured error |
 | 3 | `next_asr_number` excludes old slug files | Regex `r"^ASR-(\d+)\.md$"` anchored — `ASR-NNN-slug.md` excluded; new files start at `ASR-0001.md` |
 | 4 | Requirement text excluded from `asr_search` results | Keeps output compact; `path` field enables callers to use `asr_read` for full content |
