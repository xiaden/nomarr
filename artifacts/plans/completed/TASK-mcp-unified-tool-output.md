# Task: Unify MCP Tool Output into Single ToolOutput DTO

## Problem Statement

The MCP tool output layer (`mcp_output_helper.py`) has two DTOs (`ToolResult`, `ToolResultWithLinks`) that produce `CallToolResult` objects. All tools in `server.py` are now on these DTOs (the legacy `wrap_*` functions have been fully migrated). But the two-DTO design still has problems:

1. **Two DTOs for one concept.** `ToolResult` and `ToolResultWithLinks` differ only by whether file links exist — a presentation detail, not a domain distinction. Tools like `lint_project_backend`, `locate_module_symbol`, and `trace_module_calls` branch at runtime to pick which DTO to use.

2. **Untyped result bag.** Every tool passes `dict[str, Any]` with ad-hoc keys to `result=`. The DTO serializes whatever it gets — there's no contract for what's metadata vs what's content.

3. **Text extraction is a side-channel hack.** `text_field_keys` and `nested_text_field_paths` pop keys from the result dict to promote them to separate `TextContent` items. The tool has to know which magic field names trigger extraction.

4. **Error handling is scattered.** `is_error` flag on the DTO, `"error"` key in the result dict, sometimes both. No single channel for errors.

5. **`user_summary` exists on `ToolResult` but not `ToolResultWithLinks`**, which auto-generates from file links. Inconsistent API.

The fix: one `ToolOutput` dataclass with five explicit content channels (`breadcrumb`, `assistant_content`, `metadata`, `error`, `file_links`). Tools explicitly declare what the model should see — no magic field extraction, no runtime DTO selection.

## Phases

### Phase 1: Build ToolOutput DTO

- [x] Design and implement `ToolOutput` dataclass in `mcp_output_helper.py` with fields: `tool_name` (str), `breadcrumb` (str, default ""), `assistant_content` (list[str], default []), `metadata` (dict[str, Any], default {}), `error` (str | None, default None), `file_links` (list[FileLink], default [])
    **Notes:** Implemented ToolOutput dataclass in mcp_output_helper.py (lines 253-417). Fields: tool_name (str), breadcrumb (str, default ""), assistant_content (list[str] | None), metadata (dict[str, Any] | None), error (str | None), file_links (list[FileLink] | None). lint_project_backend passed clean.
- [x] Implement `ToolOutput.to_call_tool_result()` that builds `CallToolResult` with content array: (1) user breadcrumb with `audience=["user"]` and `_meta` from file_links, (2) error TextContent if error is set, (3) assistant_content items with `audience=["assistant"], priority=1.0`, (4) JSON metadata blob with no audience restriction. Set `isError=True` when error is set.
    **Notes:** Implemented as part of P1-S1. to_call_tool_result() builds content array: (1) user breadcrumb with audience=["user"] and _meta, (2) error TextContent if error set, (3) assistant_content with audience=["assistant"] priority=1.0, (4) JSON metadata. isError=True when error is set.
- [x] Add breadcrumb auto-generation: if `breadcrumb` is empty string, build it from `tool_name` + `file_links` (reuse `_build_user_summary` and `make_file_markdown_link` logic). If no file_links, use `[tool_name]` prefix only.
    **Notes:** Implemented as part of P1-S1. _build_breadcrumb() auto-generates from tool_name + file_links when breadcrumb is empty. Uses make_file_markdown_link and _format_line_info. Falls back to [tool_name] prefix only when no file_links.
- [x] Verify `ToolOutput` handles: no file links, single file link, multiple file links, error-only, mixed error+partial results. Run `lint_project_backend(path="code-intel")`.
    **Notes:** Verified 6 edge cases via runtime assertions: no file links, single file link, multiple file links, error-only, mixed error+partial results, no metadata. All passed. lint_project_backend(path="code-intel") clean (0 errors).

### Phase 2: Migrate All Tools to ToolOutput

- [x] Migrate simple-result tools (no file links, no text extraction): `list_project_directory_tree`, `list_project_routes`, `analyze_project_api_coverage`, `py_introspect`, `edit_file_move_by_content`, `edit_file_replace_by_content`
    **Notes:** Migrated 6 tools from ToolResult to ToolOutput: list_project_directory_tree (L281), list_project_routes (L466), analyze_project_api_coverage (L531), py_introspect (L1256), edit_file_move_by_content (L855), edit_file_replace_by_content (L924). Added ToolOutput to imports (L63).
- [x] Migrate read tools with text extraction: `read_module_api`, `read_module_source`, `read_file_symbol_at_line` — replace `text_field_keys=["source"]` with explicit `assistant_content=[result.pop("source")]`
    **Notes:** Migrated 3 tools: read_module_api (L300, eliminated branching), read_module_source (L329, explicit source pop), read_file_symbol_at_line (L363, explicit source pop). No more text_field_keys usage.
- [x] Migrate read tools with nested text extraction: `read_file_line_range`, `read_file_line` — replace `nested_text_field_paths` with explicit extraction of `requested.content` and `imports.content` before building ToolOutput
    **Notes:** Migrated read_file_line_range (L689) and read_file_line (L738). Replaced nested_text_field_paths with explicit extraction of requested.content and imports.content into assistant_content list.
- [x] Migrate navigation tools with conditional branching: `locate_module_symbol`, `search_file_text`, `trace_module_calls`, `trace_project_endpoint` — unify each to single ToolOutput construction with `file_links=[]` when none exist
    **Notes:** Migrated 4 tools, eliminated all conditional DTO branching: locate_module_symbol (L405), trace_module_calls (L440), trace_project_endpoint (L493), search_file_text (L773). Each now uses single ToolOutput with file_links=None when no files found.
- [x] Migrate lint tools: `lint_project_backend` (3 return paths), `lint_project_frontend` (4 return paths) — unify each to single ToolOutput construction, `file_links` populated or empty, `error` set for error paths
    **Notes:** Migrated lint_project_backend (L572, eliminated 3 return paths to 1) and lint_project_frontend (L606, eliminated 4 return paths to 1). Both now use single ToolOutput with conditional breadcrumb/error/file_links.
- [x] Migrate edit tools: `edit_file_replace_string`, `edit_file_move`, `edit_file_create`, `edit_file_replace_content`, `edit_file_insert_at_boundary`, `edit_file_insert_at_line`, `edit_file_copy_paste_text`
    **Notes:** Migrated 7 edit tools: edit_file_replace_string, edit_file_move, edit_file_create, edit_file_replace_content, edit_file_insert_at_boundary, edit_file_insert_at_line, edit_file_copy_paste_text. All eliminated conditional branching between ToolResult/ToolResultWithLinks.
- [x] Migrate plan tools: `plan_read`, `plan_complete_step`
    **Notes:** Migrated plan_read (L937) and plan_complete_step (L977). Both eliminated conditional branching. plan_complete_step error path now uses ToolOutput(error=...) instead of ToolResult(is_error=True).
- [x] Run `lint_project_backend(path="code-intel")` to verify all migrations
    **Notes:** lint_project_backend(path="code-intel") passes clean. Fixed one E501 line-too-long in plan_complete_step error path (L984). 0 errors across 6 files.
      E501 fix verified clean on re-lint.

### Phase 3: Cleanup

- [x] Delete `ToolResult` and `ToolResultWithLinks` classes from `mcp_output_helper.py`
    **Notes:** Deleted ToolResult class (L188-229). ToolResultWithLinks was already absent (only in docstring comment). Updated module docstring. Removed import copy.
- [x] Delete helper functions absorbed into ToolOutput: `_build_content_items`, `_extract_text_blobs`, `_extract_nested_text_blobs`, `extract_text_blobs`, `extract_nested_text_blobs`, and all legacy `wrap_*` functions
    **Notes:** Deleted _build_content_items (L135-180), _extract_text_blobs (L75-93), _extract_nested_text_blobs (L96-127). Cleaned orphaned section headers. Deleted test file test_extract_nested_text_blobs.py.
- [x] Update imports in `server.py` to import only `ToolOutput` and `FileLink` from `mcp_output_helper`. Verify no other modules import deleted symbols. Run `lint_project_backend(path="code-intel")`.
    **Notes:** server.py imports already clean (only FileLink, ToolOutput). No other files reference deleted symbols. Lint clean (0 errors). Runtime verified: ToolResult/ToolResultWithLinks/helpers raise ImportError, ToolOutput works.

## Completion Criteria

- Every tool in `server.py` returns `ToolOutput(...).to_call_tool_result()` — one DTO, one call pattern
- No conditional branching between DTO types in tool wrapper functions
- No `text_field_keys` or `nested_text_field_paths` magic — tools explicitly build `assistant_content`
- `mcp_output_helper.py` exports exactly: `ToolOutput`, `FileLink`, `make_file_markdown_link`
- Error results use `ToolOutput(error=...)` not `is_error=True` + error-in-dict
- All assistant content (source code, file content) arrives as plaintext `TextContent` items, not JSON-escaped in metadata
- User breadcrumbs display correctly with clickable file links
- `lint_project_backend(path="code-intel")` passes clean

## References

- [mcp_output_helper.py](code-intel/src/mcp_code_intel/helpers/mcp_output_helper.py) — current DTOs
- [server.py](code-intel/src/mcp_code_intel/server.py) — all tool wrapper functions (46 ToolResult/ToolResultWithLinks call sites)
- [TASK-mcp-output-dto-consolidation.md](plans/TASK-mcp-output-dto-consolidation.md) — predecessor plan (fully completed, superseded by this plan)
