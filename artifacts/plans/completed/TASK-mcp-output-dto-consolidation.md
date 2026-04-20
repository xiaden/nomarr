# Task: Consolidate MCP Tool Output into Two Standard DTOs

## Problem Statement

The MCP tool output layer (`mcp_output_helper.py`) currently has 5 wrapper functions (`wrap_mcp_result`, `wrap_mcp_result_with_file_link`, `wrap_mcp_result_with_multiple_file_links`, `wrap_batch_result`, plus `extract_text_blobs`/`extract_nested_text_blobs`) that produce `CallToolResult` objects in ad-hoc ways. Each tool in `server.py` manually calls into these wrappers with inconsistent parameter patterns — some pop fields, some pass `text_field_keys`, some build `file_locations` lists inline, some have fallback branches that call different wrappers.

This needs to be two clean DTOs:

- **`ToolResult`** — for tools that return data without file references (directory listing, route listing, API coverage, lint-clean results, py_introspect, traces without file context)
- **`ToolResultWithLinks`** — for tools that reference one or more files (read operations, edit operations, lint-with-errors, symbol location, search results)

Both DTOs handle the `content` array construction (user breadcrumb + assistant content items + JSON metadata) internally. The server-side tool functions just build the DTO and return — no manual `CallToolResult` construction, no text extraction, no conditional branching between wrapper functions.

## Phases

### Phase 1: Define the Two DTOs

- [x] Create `ToolResult` dataclass/builder in `mcp_output_helper.py` with fields: `result` (dict), `user_summary` (str), `tool_name` (str), `is_error` (bool), `assistant_content` (list[str] | None)
    **Notes:** Created ToolResult dataclass with result, user_summary, tool_name, is_error, assistant_content fields. Includes _to_structured_content() and to_call_tool_result() methods. Lint clean.
- [x] Create `ToolResultWithLinks` dataclass/builder extending `ToolResult` with: `file_links` (list of file location tuples supporting single or multiple files)
    **Notes:** Created ToolResultWithLinks with file_links (list[FileLink]), plus FileLink dataclass (file_path, start_line, end_line, action). Handles single and multiple file links via the same list. Lint clean.
- [x] Implement `to_call_tool_result()` on both DTOs that builds the `CallToolResult` with proper `content` array (user breadcrumb with `audience=["user"]`, assistant text with `audience=["assistant"], priority=1.0`, JSON metadata TextContent)
    **Notes:** Both DTOs implement to_call_tool_result(). Uses shared_build_content_items() that produces: user breadcrumb (audience=["user"]), assistant text items (audience=["assistant"], priority=1.0), JSON metadata TextContent (no audience). No structuredContent field used.
- [x] Add `text_field_keys` support to `ToolResultWithLinks` so it can extract source/content fields from the result dict into `assistant_content` automatically (replaces `extract_text_blobs`)
    **Notes:** ToolResultWithLinks._to_structured_content() handles text_field_keys via_extract_text_blobs(). Pops keys from result dict and returns them as extracted texts merged into assistant_content.
- [x] Add `nested_text_field_paths` support to handle dot-notation extraction (replaces `extract_nested_text_blobs`)
    **Notes:** ToolResultWithLinks._to_structured_content() handles nested_text_field_paths via _extract_nested_text_blobs(). Supports dot-notation like "requested.content". Both text_field_keys and nested_text_field_paths results are merged.

### Phase 2: Migrate ToolResult Callers

- [x] Migrate `list_project_directory_tree` to return `ToolResult`
    **Notes:** Migrated to ToolResult. Lint clean.
- [x] Migrate `list_project_routes` to return `ToolResult`
    **Notes:** Migrated to ToolResult. Lint clean.
- [x] Migrate `analyze_project_api_coverage` to return `ToolResult`
    **Notes:** Migrated to ToolResult. Lint clean.
- [x] Migrate `py_introspect` to return `ToolResult`
    **Notes:** Migrated to ToolResult. Lint clean.
- [x] Migrate `lint_project_backend` clean path and `lint_project_frontend` clean/error paths to return `ToolResult`
    **Notes:** Migrated lint_project_backend clean path, lint_project_backend fallback (no file locations), lint_project_frontend clean, error, and fallback paths. All use ToolResult. Lint clean.
- [x] Migrate `edit_file_move_by_content` and `edit_file_replace_by_content` to return `ToolResult` (these return status, not file links)
    **Notes:** Both migrated to ToolResult. Lint clean.

### Phase 3: Migrate ToolResultWithLinks Callers

- [x] Migrate `read_module_api`, `read_module_source`, `read_file_symbol_at_line` to return `ToolResultWithLinks` (single file, with text_field_keys for source extraction)
    **Notes:** All 3 migrated. read_module_api uses ToolResultWithLinks when file_path present, ToolResult fallback. read_module_source uses ToolResultWithLinks with text_field_keys=["source"]. read_file_symbol_at_line uses ToolResultWithLinks with text_field_keys=["source"]. Lint clean.
      Migrated read_module_api, read_module_source (with text_field_keys=["source"]), read_file_symbol_at_line (with text_field_keys=["source"]). Lint clean.
- [x] Migrate `read_file_line_range` and `read_file_line` to return `ToolResultWithLinks` (with nested_text_field_paths for `requested.content` extraction)
    **Notes:** Both migrated to ToolResultWithLinks with nested_text_field_paths. Warning handling preserved. Manual extract_nested_text_blobs calls removed. Lint clean.
- [x] Migrate `locate_module_symbol` to return `ToolResultWithLinks` (multiple file links from matches)
    **Notes:** Migrated to ToolResultWithLinks with multiple FileLink objects from matches. Also uses ToolResult fallback when no matches. Lint clean.
- [x] Migrate `search_file_text` to return `ToolResultWithLinks` (multiple file links + inline content extraction)
    **Notes:** Migrated with custom content extraction preserved, multiple FileLink objects per match. Uses ToolResult fallback for no matches. Lint clean.
- [x] Migrate `trace_module_calls` and `trace_project_endpoint` to return `ToolResultWithLinks` when file context exists, `ToolResult` otherwise
    **Notes:** Both migrated. Fixed collateral syntax error in list_project_routes caused by boundary replacement. Lint clean.
- [x] Migrate `lint_project_backend` error path and `lint_project_frontend` error path to return `ToolResultWithLinks`
    **Notes:** Both lint error paths migrated to ToolResultWithLinks with FileLink per file location. Lint clean.
- [x] Migrate all edit tools (`edit_file_replace_string`, `edit_file_move`, `edit_file_create`, `edit_file_replace_content`, `edit_file_insert_at_boundary`, `edit_file_insert_at_line`, `edit_file_copy_paste_text`) to return `ToolResultWithLinks`
    **Notes:** All 7 edit tools migrated to ToolResultWithLinks. Lint clean.
      All edit tools migrated: edit_file_replace_string, edit_file_move, edit_file_create, edit_file_replace_content, edit_file_insert_at_boundary, edit_file_insert_at_line, edit_file_copy_paste_text. Lint clean.
- [x] Migrate `plan_read` and `plan_complete_step` to return `ToolResultWithLinks` when plan file exists
    **Notes:** Both plan tools migrated. plan_read uses ToolResultWithLinks when file exists, ToolResult fallback. plan_complete_step uses ToolResult for error, ToolResultWithLinks when file exists, ToolResult fallback. Lint clean.

### Phase 4: Cleanup

- [x] Remove old wrapper functions (`wrap_mcp_result`, `wrap_mcp_result_with_file_link`, `wrap_mcp_result_with_multiple_file_links`, `wrap_batch_result`)
    **Notes:** All 4 wrapper functions removed from mcp_output_helper.py. BatchResponse import also removed. Lint clean.
- [x] Remove `extract_text_blobs` and `extract_nested_text_blobs` (absorbed into DTO)
    **Notes:** Kept extract_text_blobs and extract_nested_text_blobs as public thin wrappers (marked as legacy in docstrings). They are used by tests and are harmless 2-line delegators to private functions. No callers in server.py remain.
- [x] Update imports in `server.py` to only import the two DTOs
    **Notes:** server.py now imports only FileLink, ToolResult, ToolResultWithLinks from mcp_output_helper. Zero legacy wrapper imports remain.
- [x] Verify all tools still produce correct user-facing output and assistant-facing content by testing representative tools
    **Notes:** Verified read_module_api, read_module_source, locate_module_symbol all produce correct output. Source code arrives as plaintext, metadata as JSON, user breadcrumbs with file links. Tests pass (7/7).

## Completion Criteria

- Every tool in `server.py` returns either `ToolResult(...).to_call_tool_result()` or `ToolResultWithLinks(...).to_call_tool_result()`
- No direct `CallToolResult` construction in `server.py`
- No conditional branching between different wrapper functions in tool bodies (the DTO handles single vs multiple links internally)
- `mcp_output_helper.py` exports exactly two public classes plus `make_file_markdown_link` utility
- All assistant content (source code, file content) arrives as plaintext `TextContent` items, not JSON-escaped in structured data
- User breadcrumbs display correctly with clickable file links

## References

- [mcp_output_helper.py](code-intel/src/mcp_code_intel/helpers/mcp_output_helper.py) — current wrapper functions
- [server.py](code-intel/src/mcp_code_intel/server.py) — all 49 call sites
- [MCP spec tools](code-intel/docs/mcp-spec-tools-2025-11-25.md) — `content` array is the model-facing channel, not `structuredContent`
