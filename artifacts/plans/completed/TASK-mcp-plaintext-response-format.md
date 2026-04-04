# Task: Extract file content from structuredContent into plain text assistant content

## Problem Statement

MCP tool responses currently embed file content as JSON-escaped strings inside `structuredContent` dicts. For tools like `read_file_line_range` and `read_file_line`, the actual code content is nested under `requested.content` (and optionally `imports.content`), which means the LLM receives it as `\r\n`-escaped, `\"`-escaped JSON string values rather than plain text.

This wastes tokens on escape characters and delivers content in a format less aligned with the LLM's training distribution (code in markdown/plain text vs code inside JSON strings). The infrastructure for extracting content into separate plain-text `TextContent` items with `audience=["assistant"]` already exists (`extract_text_blobs`, `assistant_content` parameter on `wrap_mcp_result`) and is already used by `read_module_source` and `read_file_symbol_at_line`. The gap is that `read_file_line_range` and `read_file_line` don't use this pattern, and their content is nested (not top-level keys), which `extract_text_blobs` can't handle.

## Phases

### Phase 1: Enhance content extraction for nested keys

- [x] Add `extract_nested_text_blobs` function to `mcp_output_helper.py` that handles dot-notation paths (e.g., `requested.content`, `imports.content`) — extracts values from nested dicts and removes them from the result
    **Notes:** Added `extract_nested_text_blobs` at lines 63–103 in mcp_output_helper.py. Supports dot-notation paths (e.g., `requested.content`), deep-copies result, navigates to parent, pops leaf key. Lint clean (0 errors).
- [x] Add unit tests for `extract_nested_text_blobs` covering: simple top-level key, nested key, multiple nested keys, missing keys, empty values
    **Notes:** Created code-intel/tests/test_extract_nested_text_blobs.py with 7 tests covering all specified cases. All 7 passed.

### Phase 2: Update read tool handlers to extract content

- [x] Update `read_file_line_range` server handler to extract `requested.content` and `imports.content` into `assistant_content` plain text items, keeping only metadata (path, start, end) in `structuredContent`
    **Notes:** Added `extract_nested_text_blobs` import to server.py. Updated `read_file_line_range` handler (lines 652–674) to extract `requested.content` and `imports.content` into plain text `assistant_content` via `extract_nested_text_blobs`. Also added `assistant_content` parameter to `wrap_mcp_result_with_file_link` to support forwarding pre-extracted content. Lint clean.
- [x] Update `read_file_line` server handler with the same extraction pattern
    **Notes:** Updated `read_file_line` handler (lines 698–717) with identical extraction pattern: `extract_nested_text_blobs` for `requested.content` and `imports.content`, passed as `assistant_content`. Lint clean.
- [x] Verify both tools return correct responses by calling them and inspecting output structure
    **Notes:** Verified after server restart: `read_file_line_range` structuredContent shows `requested: {start, end}` with no `content` key. `read_file_line` same pattern. `include_imports=True` extraction also works. Non-Python files (package.json) also correct. Content delivered as separate plain text items.

### Phase 3: Validate

- [x] Run `lint_project_backend(path="code-intel")` and fix any errors
    **Notes:** Ran `lint_project_backend(path="code-intel")` — 0 errors, 3 files checked, all clean.
- [x] Run existing tests in `code-intel/tests/` to verify no regressions
    **Notes:** Ran `pytest tests/ -v` in code-intel: 84 passed, 9 failed, 1 skipped. All 7 new `test_extract_nested_text_blobs` tests passed. All 9 failures are pre-existing in unrelated test files (test_file_create_new, test_file_insert_text, test_file_replace) covering large file handling, content-based insert tools, and binary file edge cases. No regressions from this change.

## Completion Criteria

- `read_file_line_range` and `read_file_line` return file content as plain text `TextContent` items with `audience=["assistant"]`, not as JSON-escaped strings inside `structuredContent`
- `structuredContent` retains metadata only (path, line numbers, warnings)
- All existing extraction patterns (`read_module_source`, `read_file_symbol_at_line`, `search_file_text`) continue working unchanged
- Lint passes, existing tests pass

## References

- `code-intel/src/mcp_code_intel/helpers/mcp_output_helper.py` — extraction infrastructure
- `code-intel/src/mcp_code_intel/server.py` — tool handler wrappers
- `code-intel/src/mcp_code_intel/tools/read_file_range.py` — read_file_range implementation
- `code-intel/src/mcp_code_intel/tools/read_file_line.py` — read_file_line implementation
