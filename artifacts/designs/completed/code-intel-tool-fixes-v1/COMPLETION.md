# Code-Intel MCP Tool Reliability Fixes — Completion Manifest

**Completed:** 2026-04-02
**Design doc:** `DD-code-intel-tool-fixes-v1.md`
**Parts README:** `code-intel-tool-fixes-v1/README.md`
**Contracts ledger:** `code-intel-tool-fixes-v1/CONTRACTS.md`

---

## Execution Summary

| Plan | Title | Rounds | Fix Plans | Status |
|---|---|---|---|---|
| A | Shared Helper Fixes | 2 | — | PASS |
| B | Insert Text EOL Fix | 1 | — | PASS |
| C | Python Nav Fixes | 2 | — | PASS |

## Design Deviations

- Plan A required an amendment (Phase 3) to update callers of `find_content_boundaries()` that used bare 2-tuple unpacking. The design doc assumed callers used `*` unpacking but they used `start, end = result` — all 4 call sites updated.

## Key Decisions

- Tests couldn't be run inside Exec-Manager sub-agents (no terminal tool). Manual pytest confirmation performed after each plan.
- Plan A and C executed in parallel (Round 1, independent), Plan B in Round 2 (depended on Plan A's tab_warning change).

## Files Created/Modified

### Helpers
- `code-intel/src/mcp_code_intel/helpers/content_boundaries.py` (modified — ±2 tolerance retry, 3-tuple return)
- `code-intel/src/mcp_code_intel/helpers/file_helpers.py` (modified — tab rejection → tab_warning metadata)

### Tools
- `code-intel/src/mcp_code_intel/tools/edit_file_replace_by_content.py` (modified — 3-tuple handling)
- `code-intel/src/mcp_code_intel/tools/edit_file_move_by_content.py` (modified — 3-tuple handling)
- `code-intel/src/mcp_code_intel/tools/edit_file_insert_text.py` (modified — CRLF normalization, trailing newline fix, tab_warning propagation)
- `code-intel/src/mcp_code_intel/tools/locate_module_symbol.py` (modified — parent_filter guard, path-segment matching)
- `code-intel/src/mcp_code_intel/tools/read_module_source.py` (modified — iterative N-level AST walk)
- `code-intel/src/mcp_code_intel/server.py` (modified — deprecated tool removal)

### Deprecated (moved to tools/deprecated/)
- `code-intel/src/mcp_code_intel/tools/deprecated/analyze_project_api_coverage.py`
- `code-intel/src/mcp_code_intel/tools/deprecated/edit_file_copy_paste_text.py`
- `code-intel/src/mcp_code_intel/tools/deprecated/list_project_routes.py`

### Tests
- `code-intel/tests/test_content_boundaries.py` (modified — tolerance tests)
- `code-intel/tests/test_file_helpers.py` (created — tab warning tests)
- `code-intel/tests/test_locate_module_symbol.py` (modified — parent_filter, path-segment tests)
- `code-intel/tests/test_read_module_source.py` (modified — N-level AST tests)
- `code-intel/tests/test_file_insert_text.py` (modified — fixed 5 broken tests, added 4 new regression tests)

## Final Lint Status

- Backend: PASS (zero errors on all changed files; 1 pre-existing E501 in server.py line 1258 unrelated)
- Frontend: N/A
