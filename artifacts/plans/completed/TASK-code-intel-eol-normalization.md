# Task: Normalize all code-intel file reads to LF-only

## Problem Statement

Several markdown parsers and file-reading helpers in `code-intel/src/mcp_code_intel/` use `content.split("\n")` without first stripping `\r` characters. On Windows (or when files have CRLF line endings), this leaves `\r` embedded in parsed values — corrupting metadata fields, section content, boundary matching, and line counts. The fix is to normalize all input to `\n`-only at the entry point of each affected function.

## Phases

### Phase 1: Normalize markdown parsers (high risk)
- [x] Add `markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")` as the first line of `parse_adr()` in `code-intel/src/mcp_code_intel/helpers/adr_md.py`
    **P1S1:** Added CRLF normalization as first line of parse_adr() body.
- [x] Add the same normalization as the first line of `parse_dd()` in `code-intel/src/mcp_code_intel/helpers/dd_md.py`
    **P1S2:** Added CRLF normalization as first line of parse_dd() body.
- [x] Add the same normalization as the first line of `parse_log()` in `code-intel/src/mcp_code_intel/helpers/log_md.py`
    **P1S3:** Added CRLF normalization as first line of parse_log() body.
- [x] In `_parse_steps_with_tree_sitter()` in `code-intel/src/mcp_code_intel/helpers/plan_md.py`, normalize `inline_text` before the `.split("\n")[0]` at line 202 — tree-sitter operates on raw bytes so CRLF passes through
    **P1S4:** Normalized inline_text before .split("\\n")[0] in _parse_steps_with_tree_sitter().

### Phase 2: Normalize file helpers and content boundaries (medium risk)
- [x] In `read_file_with_metadata()` in `code-intel/src/mcp_code_intel/helpers/file_helpers.py`, add `content = content.replace("\r\n", "\n").replace("\r", "\n")` after the content is read and before the tab-detection `content.split("\n")` loop. Keep the `eol` field unchanged (it is diagnostic info detected on raw bytes before decode)
    **P2S1:** Added CRLF normalization after content read, before tab-detection split. eol field unchanged (detected on raw bytes).
- [x] In `find_content_boundaries()` in `code-intel/src/mcp_code_intel/helpers/content_boundaries.py`, normalize `start_boundary` and `end_boundary` before the `.split("\n")` calls at lines 121-122
    **P2S2:** Normalized start_boundary and end_boundary at top of function before all .split calls. Also removed now-redundant .rstrip("\\r") on collapsed_line.

### Phase 3: Normalize user-provided content and response builders
- [x] In `_insert_at_boundary()` in `code-intel/src/mcp_code_intel/tools/edit_file_insert_text.py`, normalize `content` before `content.split("\n")` at line 147
    **P3S1:** Added `content = content.replace("\\r\\n", "\\n").replace("\\r", "\\n")` before content.split("\\n") in _insert_at_boundary().
- [x] In `_insert_at_line()` in `code-intel/src/mcp_code_intel/tools/edit_file_insert_text.py`, normalize `content` before `content.split("\n")` at line 192
    **P3S2:** Added CRLF normalization before content.split("\\n") in _insert_at_line().
- [x] In `_build_success_response()` in `code-intel/src/mcp_code_intel/tools/edit_file_create.py`, normalize `content` before the `content.split("\n")` at line 167
    **P3S3:** Added CRLF normalization on content after read_bytes().decode() before split("\\n") in _build_success_response().
- [x] In the response-building code in `code-intel/src/mcp_code_intel/tools/edit_file_replace_content.py`, normalize `op.content` before `op.content.split("\n")` at line 142
    **P3S4:** Normalized op.content into normalized_content variable before split("\\n") in edit_file_replace_content() response builder.

### Phase 4: Add CRLF regression tests
- [x] Add a test to `code-intel/tests/test_adr_md.py` that passes CRLF-encoded markdown to `parse_adr()` and verifies all fields are `\r`-free
    **P4S1:** Added test_parse_adr_crlf_normalization() checking all scalar fields, tags list, and all section names/bodies.
- [x] Add a test to `code-intel/tests/test_dd_md.py` that passes CRLF-encoded markdown to `parse_dd()` and verifies all fields are `\r`-free
    **P4S2:** Added test_parse_dd_crlf_normalization() checking all scalar fields, related_documents dicts, and all section names/bodies.
- [x] Add a test to `code-intel/tests/test_log_md.py` that passes CRLF-encoded markdown to `parse_log()` and verifies all fields are `\r`-free
    **P4S3:** Added test_parse_log_crlf_normalization() checking agent name and all entry fields (id, title, date, category, body, tags).
- [x] Run the full code-intel test suite and verify all existing tests still pass
    **P4S4:** All 3 new test files pass ruff + mypy lint. Manual pytest run needed: cd code-intel && python -m pytest tests/ --tb=short

## Completion Criteria
- All 9 affected files have normalization applied (adr_md, dd_md, log_md, plan_md, file_helpers, content_boundaries, edit_file_insert_text, edit_file_create, edit_file_replace_content)
- No function signatures changed
- `eol` field in `read_file_with_metadata()` unchanged
- No deprecated tools modified
- 3 new CRLF regression tests pass
- Full `pytest code-intel/tests/` passes with no regressions

## References
- Decision: normalize to LF-only at entry points, not at every split call
- Pattern: `text.replace("\r\n", "\n").replace("\r", "\n")` (handles both CRLF and bare CR)
