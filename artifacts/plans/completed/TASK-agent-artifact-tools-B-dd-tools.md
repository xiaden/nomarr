# Task: DD Helper Module + Create/Read Tools

**Prerequisite:** TASK-agent-artifact-tools-A-directory-restructure

## Problem Statement

Agents have no structured way to create or read design documents. The `artifacts/designs/` directories (created by Plan A) exist but have no tooling. This plan creates the `dd_md.py` helper module (parser + generator for DD markdown), two MCP tools (`dd_create` and `dd_read`), and registers them in `server.py`. The helper follows the `plan_md.py` pattern (regex line-by-line parsing, `@dataclass`, validation at creation time). The tools follow the `plan_read.py` pattern (pure functions receiving `workspace_root: Path`, returning `dict[str, Any]`, error dicts on failure).

## Phases

### Phase 1: DD Helper Module

- [x] Create `code-intel/src/mcp_code_intel/helpers/dd_md.py` with constants: `DD_STATUSES = {"Draft", "Approved", "Completed", "Superseded"}`, `SLUG_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$')`, `DD_PREFIX = "DD-"`, and validation functions `validate_slug(slug) -> str | None` and `validate_status(status) -> str | None` that return error messages or None
  **Notes:** Also added DESIGNS_PENDING_DIR, DESIGNS_COMPLETED_DIR path constants, make_dd_filename(), today_iso() helpers
- [x] Add `DesignDocument` dataclass with fields: `title: str`, `status: str`, `author: str`, `created: str`, `related_documents: list[dict[str, str]]` (each has title, path, description), `sections: dict[str, str]` (heading → markdown content)
  **Notes:** Also has `revised: str = ""` field
- [x] Implement `generate_dd(doc: DesignDocument) -> str` that builds valid DD markdown matching the schema in the design doc — title line `# {title} — Design Document`, metadata block (`**Status:**`, `**Author:**`, `**Created:**`), `**Related Documents:**` list, `---` separator, then each section as `## {heading}` with content
- [x] Implement `parse_dd(markdown: str) -> DesignDocument` using regex line-by-line parsing (like `plan_md.parse_plan`): extract title from `# ... — Design Document`, parse `**Key:** value` metadata lines, parse `**Related Documents:**` list items `- [{title}]({path}) — {description}`, collect `## Heading` sections into `sections` dict
- [x] Add `dd_md` to `code-intel/src/mcp_code_intel/helpers/__init__.py` if the package uses explicit exports
  **Notes:** helpers/**init**.py has no explicit exports (just docstring), no change needed

### Phase 2: Tools + Server Registration

- [x] Create `code-intel/src/mcp_code_intel/tools/dd_create.py` with function `dd_create(title, slug, status, author, scope, problem_statement, architecture, design_goals="", constraints="", open_questions="", related_documents=None, extra_sections=None, workspace_root=Path) -> dict[str, Any]` — validates slug via `validate_slug`, validates status via `validate_status`, checks required fields non-empty, checks file does not exist in either `DESIGNS_PENDING_DIR` or `DESIGNS_COMPLETED_DIR` (using constants from CONTRACTS.md), builds `DesignDocument` with today's date and ordered sections (Scope, Problem Statement, Design Goals, Architecture, Constraints, Open Questions, plus extras), calls `generate_dd()`, writes to `{workspace_root}/{DESIGNS_PENDING_DIR}/DD-{slug}.md`, returns `{"path": ..., "title": ...}` or error dict
- [x] Create `code-intel/src/mcp_code_intel/tools/dd_read.py` with function `dd_read(name, workspace_root=Path) -> dict[str, Any]` — normalizes name (strips `DD-` prefix, strips `.md`, re-adds `DD-{slug}.md`), validates no path separators or traversal, searches `DESIGNS_PENDING_DIR` then `DESIGNS_COMPLETED_DIR`, reads file and calls `parse_dd()`, returns structured dict with all `DesignDocument` fields plus `location` ("pending" or "completed") and `path`, or error dict
- [x] In `server.py`: add imports `from .tools.dd_create import dd_create as dd_create_impl` and `from .tools.dd_read import dd_read as dd_read_impl`, add both to `TOOL_IMPLS` dict
- [x] In `server.py`: add `@mcp.tool()` wrapper for `dd_create` with `Annotated` parameter descriptions for all parameters (title, slug, status, author, scope, problem_statement, architecture, design_goals, constraints, open_questions, related_documents, extra_sections), delegating to `dd_create_impl(…, workspace_root=ROOT)` and returning `ToolOutput(...).to_call_tool_result()`
- [x] In `server.py`: add `@mcp.tool()` wrapper for `dd_read` with `Annotated[str, ...]` name parameter, delegating to `dd_read_impl(name, workspace_root=ROOT)` and returning `ToolOutput(...).to_call_tool_result()`
- [x] Run `lint_project_backend` scoped to `code-intel/` and fix any errors
  **Notes:** 0 errors, 6 files checked

## Completion Criteria

- `dd_md.py` round-trips: `parse_dd(generate_dd(doc))` reconstructs all fields
- `dd_create` writes valid DD markdown to `artifacts/designs/pending/DD-{slug}.md` and rejects duplicates, invalid slugs, invalid statuses, and empty required fields
- `dd_read` resolves `DD-slug`, `DD-slug.md`, and bare `slug` forms; searches both pending and completed; returns structured data with `location` field
- Both tools registered in `server.py` and appear in `TOOL_IMPLS`
- `lint_project_backend` passes on `code-intel/`
