# Task: ADR Helper Module + Create/Read/Search Tools

**Prerequisite:** TASK-agent-artifact-tools-A-directory-restructure

## Problem Statement

Architecture decisions are scattered across chat logs, plan annotations, and ad-hoc markdown files. The `artifacts/decisions/` directory (created by Plan A) exists but has no tooling. This plan creates the `adr_md.py` helper module (parser, generator, metadata-only parser for search performance, and auto-numbering), three MCP tools (`adr_create`, `adr_read`, `adr_search`), and registers them in `server.py`. The helper follows the `plan_md.py` pattern (regex line-by-line parsing, `@dataclass`, validation at creation time). The tools follow the `plan_read.py` pattern (pure functions receiving `workspace_root: Path`, returning `dict[str, Any]`, error dicts on failure).

## Phases

### Phase 1: ADR Helper Module
- [x] Create `code-intel/src/mcp_code_intel/helpers/adr_md.py` with constants: `ADR_STATUSES = {"Proposed", "Accepted", "Deprecated", "Superseded"}`, `SOURCE_LOG_PATTERN = re.compile(r'^[a-z][a-z0-9-]*[a-z0-9]#L\d+$')`, `DECISIONS_DIR = "artifacts/decisions"`, `ADR_PREFIX = "ADR-"`, title-slug function `_slugify(title: str) -> str` (lowercase, replace non-alphanumeric with hyphens, collapse runs, strip leading/trailing hyphens), and validation functions `validate_status(status) -> str | None`, `validate_source_log(source_log) -> str | None` that return error messages or None
- [x] Add `ADR` dataclass with fields: `number: int`, `title: str`, `status: str`, `date: str`, `tags: list[str]`, `source_log: str | None`, `sections: dict[str, str]` (heading → markdown content)
- [x] Implement `generate_adr(adr: ADR) -> str` that builds valid ADR markdown matching the design doc schema — title line `# ADR-{NNN}: {title}` (NNN zero-padded 3 digits), metadata block (`**Status:**`, `**Date:**`, `**Tags:**`, optional `**Source Log:**`), then each section as `## {heading}` with content (Context, Decision, Consequences first, then extras, then References last if present)
- [x] Implement `parse_adr(markdown: str) -> ADR` using regex line-by-line parsing: extract title and number from `# ADR-{NNN}: {title}`, parse `**Key:** value` metadata lines (Status, Date, Tags as comma-split list, optional Source Log), collect `## Heading` sections into `sections` dict
- [x] Implement `parse_adr_metadata(markdown: str) -> dict` that parses only the header up to the first `## ` line — returns `{"number": int, "title": str, "status": str, "date": str, "tags": list[str], "source_log": str | None}` without parsing section bodies (for search performance)
- [x] Implement `next_adr_number(workspace_root: Path) -> int` that globs `artifacts/decisions/ADR-*.md`, extracts the highest NNN from filenames, and returns NNN+1 (or 1 if no ADRs exist)

### Phase 2: Tools + Server Registration
- [x] Create `code-intel/src/mcp_code_intel/tools/adr_create.py` with function `adr_create(title, status, tags, context, decision, consequences, references="", source_log="", extra_sections=None, workspace_root=Path) -> dict[str, Any]` — validates status via `validate_status`, validates at least one tag, validates required sections non-empty, validates `source_log` format via `validate_source_log` if provided, calls `next_adr_number` to get number, slugifies title, builds `ADR` dataclass with today's date and ordered sections (Context, Decision, Consequences, plus extras, References last), calls `generate_adr()`, writes to `{workspace_root}/{DECISIONS_DIR}/ADR-{NNN}-{slug}.md` with retry up to 3 times on `FileExistsError` (re-scanning for next number each retry), returns `{"path": ..., "number": ..., "title": ...}` or error dict
- [x] Create `code-intel/src/mcp_code_intel/tools/adr_read.py` with function `adr_read(name, workspace_root=Path) -> dict[str, Any]` — normalizes name (strips `ADR-` prefix, strips `.md`), validates no path separators or traversal, if name is purely numeric (e.g. `003`) globs for `ADR-003-*.md` in `DECISIONS_DIR`, otherwise resolves as `ADR-{name}.md`, reads file and calls `parse_adr()`, returns structured dict with all `ADR` fields plus `path`, or error dict
- [x] Create `code-intel/src/mcp_code_intel/tools/adr_search.py` with function `adr_search(query="", tag="", status="", limit=50, workspace_root=Path) -> dict[str, Any]` — caps limit at 50, globs `ADR-*.md` in `DECISIONS_DIR`, for each file calls `parse_adr_metadata()` (or `parse_adr()` if `query` is non-empty for body search), filters by exact tag match if `tag` provided, filters by status if `status` provided, filters by case-insensitive substring match on title+tags+body if `query` provided, sorts by number descending, truncates to limit, returns `{"results": [...], "total": N}`
- [x] In `server.py`: add imports `from .tools.adr_create import adr_create as adr_create_impl`, `from .tools.adr_read import adr_read as adr_read_impl`, `from .tools.adr_search import adr_search as adr_search_impl`, add all three to `TOOL_IMPLS` dict
- [x] In `server.py`: add `@mcp.tool()` wrappers for `adr_create` (with `Annotated` descriptions for title, status, tags, context, decision, consequences, references, source_log, extra_sections), `adr_read` (Annotated name), and `adr_search` (Annotated query, tag, status, limit), each delegating to the `_impl` function with `workspace_root=ROOT` and returning `ToolOutput(...).to_call_tool_result()`
- [x] Run `lint_project_backend` scoped to `code-intel/` and fix any errors

## Completion Criteria
- `adr_md.py` round-trips: `parse_adr(generate_adr(adr))` reconstructs all fields
- `parse_adr_metadata` returns correct metadata without parsing section bodies
- `next_adr_number` returns 1 for empty directory, N+1 when ADRs exist
- `adr_create` writes valid ADR markdown to `artifacts/decisions/ADR-{NNN}-{slug}.md`, rejects missing tags, invalid statuses, empty required sections, and retries on collision
- `adr_read` resolves `ADR-003`, `ADR-003-use-edges`, `ADR-003-use-edges.md`, and bare `003` forms; returns structured data with `path` field
- `adr_search` filters by tag, status, and query; returns results sorted by number descending; respects limit cap of 50
- All three tools registered in `server.py` and appear in `TOOL_IMPLS`
- `lint_project_backend` passes on `code-intel/`

## References
- Design doc: `plans/dev/design-agent-artifact-tools.md` (ADR schema, adr_create/adr_read/adr_search API)
- Contracts: `plans/dev/agent-artifact-tools-parts/CONTRACTS.md`
- Helper pattern: `code-intel/src/mcp_code_intel/helpers/plan_md.py`
- Tool pattern: `code-intel/src/mcp_code_intel/tools/plan_read.py`
