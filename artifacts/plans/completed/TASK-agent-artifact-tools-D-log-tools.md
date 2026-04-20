# Task: Log Helper Module + Write/Read Tools

**Prerequisite:** TASK-agent-artifact-tools-A-directory-restructure

## Problem Statement

Operational logs (research trails, dead ends, observations) vanish when a session ends. Future agents repeat failed approaches because there is no institutional memory. The `artifacts/logs/` directory (created by Plan A) exists but has no tooling. This plan creates the `log_md.py` helper module (parser, appender, and validation for per-agent log markdown), two MCP tools (`log_write` and `log_read`), and registers them in `server.py`. The helper follows the `plan_md.py` pattern (regex line-by-line parsing, `@dataclass`, validation at creation time). The tools follow the `plan_read.py` pattern (pure functions receiving `workspace_root: Path`, returning `dict[str, Any]`, error dicts on failure). Log entries are append-only — no edit or delete.

## Phases

### Phase 1: Log Helper Module

- [x] Create `code-intel/src/mcp_code_intel/helpers/log_md.py` with constants: `CATEGORIES = {"research", "decision", "blocker", "discovery", "dead-end", "implementation", "observation"}`, `AGENT_NAME_PATTERN = re.compile(r'^[a-z][a-z0-9-]*[a-z0-9]$')`, `LOGS_DIR = "artifacts/logs"`, and validation functions `validate_category(category: str) -> str | None` and `validate_agent_name(agent: str) -> str | None` that return error messages or None
- [x] Add `LogEntry` dataclass with fields: `id: str` (e.g. "L42"), `title: str`, `date: str` (ISO 8601 UTC), `category: str`, `tags: list[str]`, `body: str`; and `AgentLog` dataclass with fields: `agent: str`, `entries: list[LogEntry]`
- [x] Implement `generate_log_header(agent: str) -> str` that returns the initial log file content: `# Agent Log: {agent}` followed by a blank line and `---`
- [x] Implement `next_entry_id(log: AgentLog) -> str` that finds the highest `L{N}` id among `log.entries` and returns `L{N+1}` (or `L1` if no entries exist)
- [x] Implement `parse_log(markdown: str) -> AgentLog` using regex line-by-line parsing: extract agent name from `# Agent Log: {name}`, split entries on `## [{id}] {title}` headings, parse `**Date:**`, `**Category:**`, `**Tags:**` (comma-split, stripped) metadata lines within each entry, collect remaining lines as body, return `AgentLog` with entries in file order
- [x] Implement `append_entry(file_path: Path, entry: LogEntry) -> None` that opens the file in append mode and writes: blank line, `## [{id}] {title}`, `**Date:** {date}`, `**Category:** {category}`, optional `**Tags:** {comma-joined tags}` (omitted if empty), blank line, body text (if non-empty), blank line, and `---` separator

### Phase 2: Tools + Server Registration

- [x] Create `code-intel/src/mcp_code_intel/tools/log_write.py` with function `log_write(agent, title, category, body="", tags=None, workspace_root=Path) -> dict[str, Any]` — validates agent via `validate_agent_name`, validates category via `validate_category`, validates title is non-empty, resolves log file path as `{workspace_root}/{LOGS_DIR}/{agent}.log.md`, creates `LOGS_DIR` directory if needed, if file does not exist writes `generate_log_header(agent)`, reads file and calls `parse_log()` to get current state, calls `next_entry_id()` for the new ID, builds `LogEntry` with current UTC timestamp (`datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")`), calls `append_entry()`, returns `{"path": ..., "entry_id": ..., "title": ...}` or error dict
- [x] Create `code-intel/src/mcp_code_intel/tools/log_read.py` with function `log_read(agent, category="", tag="", title_query="", limit=50, workspace_root=Path) -> dict[str, Any]` — validates agent via `validate_agent_name`, caps limit at 50, resolves log file path as `{workspace_root}/{LOGS_DIR}/{agent}.log.md`, returns error dict if file does not exist, reads file and calls `parse_log()`, reverses entries (newest-first), applies AND-combined filters: if `category` non-empty filters by exact match, if `tag` non-empty filters by case-insensitive match in entry tags, if `title_query` non-empty filters by case-insensitive substring in title, truncates to limit, returns `{"agent": ..., "entries": [...], "total": N}` where each entry is a dict with id, title, date, category, tags, body
- [x] In `server.py`: add imports `from .tools.log_write import log_write as log_write_impl` and `from .tools.log_read import log_read as log_read_impl`, add both to `TOOL_IMPLS` dict
- [x] In `server.py`: add `@mcp.tool()` wrapper for `log_write` with `Annotated` parameter descriptions for agent, title, category, body, tags, delegating to `log_write_impl(…, workspace_root=ROOT)` and returning `ToolOutput(tool_name="log_write", breadcrumb=..., metadata=result).to_call_tool_result()`
- [x] In `server.py`: add `@mcp.tool()` wrapper for `log_read` with `Annotated` parameter descriptions for agent, category, tag, title_query, limit, delegating to `log_read_impl(…, workspace_root=ROOT)` and returning `ToolOutput(tool_name="log_read", breadcrumb=..., metadata=result).to_call_tool_result()`
- [x] Run `lint_project_backend` scoped to `code-intel/` and fix any errors

## Completion Criteria

- `log_md.py` round-trips: `parse_log()` correctly parses output produced by `generate_log_header()` + `append_entry()` calls
- `next_entry_id` returns `L1` for empty log, `L{N+1}` when entries exist
- `validate_category` rejects values not in the 7 allowed categories
- `validate_agent_name` rejects names not matching the pattern
- `log_write` creates log file with header on first call, appends entries with auto-incrementing IDs and ISO 8601 UTC timestamps, rejects invalid agent names, invalid categories, and empty titles
- `log_read` returns entries newest-first, applies AND-combined filters for category, tag, and title_query, respects limit cap of 50, returns error for non-existent agent log
- Both tools registered in `server.py` and appear in `TOOL_IMPLS`
- `lint_project_backend` passes on `code-intel/`

## References

- Design doc: `plans/dev/design-agent-artifact-tools.md` (Log schema, log_write/log_read API)
- Contracts: `plans/dev/agent-artifact-tools-parts/CONTRACTS.md`
- Helper pattern: `code-intel/src/mcp_code_intel/helpers/plan_md.py`
- Tool pattern: `code-intel/src/mcp_code_intel/tools/plan_read.py`
