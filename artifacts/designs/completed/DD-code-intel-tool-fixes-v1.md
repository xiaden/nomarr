# Code-Intel MCP Tool Reliability Fixes — Design Document

**Status:** Draft  
**Author:** Agent  
**Created:** 2026-04-02  

---

## Scope

Fix reliability issues in 5 code-intel MCP tools: `edit_file_move_by_content`, `edit_file_replace_by_content`, `edit_file_insert_at_line` (anchor mode), `read_module_source`, and `locate_module_symbol`. Three content-boundary tools share infrastructure in `content_boundaries.py` and `file_helpers.py`. Two Python navigation tools have independent issues in resolution logic.

---

## Problem Statement

Five code-intel MCP tools routinely fail when called by AI agents. Research identified these root causes:

**Shared infrastructure (content-boundary tools):**
1. **`expected_line_count` must be exact** — agents frequently miscount by ±1, causing "No matching range" errors with confusing diagnostics
2. **Tab rejection in `read_file_with_metadata()`** — hard blocks editing any file with tab indentation (Go, Makefiles, some JS)
3. **Short boundaries** like `return`, `};` match too many lines via substring — paired with strict line-count, produces zero candidates
4. **Anchor ambiguity** — `find_anchor_line()` requires exactly 1 match; common lines like `pass`, `import os` fail

**`edit_file_insert_text` (anchor mode):**
5. **Windows EOL bug** — `content.split("\n")` leaves `\r` on lines, causing data corruption on CRLF files
6. **Trailing newline silently stripped** — `content.rstrip("\n")` removes intentional blank lines from inserted content

**`read_module_source`:**
7. **Only 2 levels of AST nesting** — can't find `Class.InnerClass.method`
8. **CWD-dependent workspace root** — `get_workspace_root()` uses `Path.cwd()` with no override; wrong CWD = all resolution fails silently

**`locate_module_symbol`:**
9. **`parent_filter` gap** — top-level functions match parent-scoped queries like `ConfigService.get_config` because `parent_class is None` short-circuits the filter
10. **Path filter uses substring** — `"services" in path` matches `microservices/` too
11. **Two-part name disambiguation** — folder check can misfire when folder and class share names

---

## Architecture

Changes are scoped to `code-intel/src/mcp_code_intel/`:

**Layer 1 — Shared helpers** (`helpers/`)
- `content_boundaries.py`: Add line-count tolerance (±2 with warning), improve diagnostics
- `file_helpers.py`: Remove tab rejection (or convert to warning), fix EOL handling in insert path

**Layer 2 — Tool implementations** (`tools/`)
- `edit_file_insert_text.py`: Fix `content.split("\n")` → `splitlines()`, fix trailing newline stripping
- `edit_file_move_by_content.py`: Benefits from Layer 1 fixes, no direct changes needed
- `edit_file_replace_by_content.py`: Benefits from Layer 1 fixes, no direct changes needed
- `read_module_source.py`: Support 3+ nesting levels in `_find_symbol_in_ast()`, accept `workspace_root` parameter
- `locate_module_symbol.py`: Fix parent_filter gap, use path-segment matching, fix disambiguation

**Layer 3 — Server wrappers** (`server.py`)
- No changes expected — wrappers are thin

**Dependency direction:** helpers → tools → server (no circular deps)

---

## Design Goals

1. **Zero-regression**: All existing passing tests continue to pass
2. **Tolerance over strictness**: Content-boundary tools should succeed on reasonable inputs, warn on ambiguity rather than fail
3. **Cross-platform**: Windows EOL bug fix, tab handling that works with all file types
4. **Minimal scope**: Fix the identified bugs; don't redesign the tools

---

## Constraints

- No changes to the MCP tool API signatures (backward compatible)
- Content-boundary tolerance must still detect genuinely wrong inputs (not just accept anything)
- `read_module_source` and `locate_module_symbol` already have workspace_root passed from server.py's ROOT — verify this before adding parameters
- Tests must be added for every fix to prevent regression

---

## Open Questions

1. Should `expected_line_count` tolerance be ±1 or ±2? (±2 recommended — agents often miss blank lines at boundaries)
2. Should tab rejection become a warning in the response, or be removed entirely? (Warning recommended — lets the tool work but alerts the agent)
3. Should `find_anchor_line()` support a `match_index` parameter for disambiguation, or just better error messages? (Better errors first, `match_index` as follow-up)

---

## Risk Assessment

**Low risk**: All changes are in code-intel tooling, not in the nomarr application itself. Tool tests in `code-intel/tests/` provide regression safety. The biggest risk is the `expected_line_count` tolerance — too loose and it masks genuinely wrong boundaries. ±2 with a warning when tolerance is used (not exact match) strikes the right balance.

---
