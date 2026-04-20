# Code-Intel MCP Tool Reliability Fixes — Contracts Ledger

**Design doc:** `artifacts/designs/pending/DD-code-intel-tool-fixes-v1.md`
**Last updated:** 2026-04-02 (initial)

---

## Architectural Rules

- All code-intel code lives in `code-intel/src/mcp_code_intel/`
- Tools are in `tools/`, shared helpers in `helpers/`
- Tools import helpers; helpers never import tools
- Tool wrapper functions in `server.py` are thin — logic stays in tool modules
- Tests go in `code-intel/tests/` (main test suite)
- `read_file_with_metadata()` is the canonical file-read entry point for editing tools
- `find_content_boundaries()` and `find_anchor_line()` are the canonical boundary-matching functions
- `atomic_write()` handles EOL normalization on write
- Error returns use `dict` with `"error"` key (not exceptions) for tool-level errors

---

## Collections & Methods

*(None yet — this feature modifies existing functions, not database collections)*

---

## API Contracts

*(No API endpoints affected — these are MCP tool internals)*

---

## Function Signature Changes (Plan A)

### `find_content_boundaries()` in `helpers/content_boundaries.py`

**Before:** `(file_lines, start_boundary, end_boundary, expected_line_count) -> tuple[int, int] | str`  
**After:** `(file_lines, start_boundary, end_boundary, expected_line_count) -> tuple[int, int] | tuple[int, int, str] | str`

- Exact match: returns `(start, end)` as before (no warning)
- Tolerance match (±2): returns `(start, end, warning_str)` — 3-tuple
- Error: returns `str` as before
- Callers use `isinstance(result, str)` for error check — unchanged and compatible
- **All callers must handle 3-tuple:** `len(match_result) == 3` → unpack `(start, end, warning)`, else 2-tuple `(start, end)` with `warning = None`. Warning propagated into tool response dict.
- Affected callers: `edit_file_replace_by_content.py` (1 site), `edit_file_move_by_content.py` (3 sites)

### `read_file_with_metadata()` in `helpers/file_helpers.py`

**Before:** Returns `{"error": "File contains tab..."}` for tab files  
**After:** Returns `{"content": ..., "mtime": ..., "eol": ..., "tab_warning": "..."}` — file is readable, warning is metadata

- Callers check `"error" in file_data` — still works (no error key for tabs now)
- New `tab_warning` key only present when tabs detected; callers may ignore it

## Function Behavior Changes (Plan B)

### `_apply_insertions_to_file()` in `tools/edit_file_insert_text.py`

**Before:** `lines = content.split("\n")` — breaks on CRLF files (leaves `\r` on each line).  
**After:** `lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")` — normalizes all EOL variants before splitting.

Also: now captures `tab_warning` from `read_file_with_metadata()` and propagates it through the response.

### `_insert_at_boundary()` in `tools/edit_file_insert_text.py`

**Before:** `content.rstrip("\n").split("\n")` — strips all trailing newlines, silently dropping intentional blank lines.  
**After:** `content.split("\n")` with single trailing empty string removal — `"a\nb\n\n"` preserves blank line as `["a", "b", ""]`.

### `_insert_at_line()` in `tools/edit_file_insert_text.py`

**Before:** Same `rstrip("\n")` bug as `_insert_at_boundary()`.  
**After:** Same fix — single trailing empty string removal preserves intentional blank lines.

## DTOs Created

*(None expected)*

---

## Function Behavior Changes (Plan C)

### `_search_tree()` in `tools/locate_module_symbol.py`

**Before:** `if parent_filter and parent_class and parent_class != parent_filter` — short-circuits on `parent_class is None`, allowing top-level functions through parent-scoped queries.  
**After:** When `parent_filter` is set and `parent_class` is None, the match is excluded. Top-level functions never match parent-scoped queries like `Class.method`.

### `locate_module_symbol()` path filter in `tools/locate_module_symbol.py`

**Before:** `if path_filter and path_filter not in relative_path` — substring matching.  
**After:** `if path_filter and f"/{path_filter}/" not in f"/{relative_path}"` — path-segment boundary matching. `services` no longer matches `microservices/`.

### `_find_symbol_in_ast()` in `tools/read_module_source.py`

**Before:** Fixed 2-level lookup (top-level symbol or Class.method). Returns `None` for 3+ parts.  
**After:** Iterative loop that walks N levels of AST nesting. Supports `Outer.Inner.method` and deeper paths.

---

## Decisions Made

 | Decision | Rationale | Plan |
 | --- | --- | --- |
 | ±2 tolerance for expected_line_count | Agents commonly miscount by 1-2 lines (blank lines at boundaries); ±2 catches most errors while still rejecting genuinely wrong inputs | initial |
 | Tab rejection → warning, not hard error | Tab indentation is valid in many languages (Go, Makefiles, JS); blocking edits entirely is wrong | initial |
 | Fix insert text EOL before other insert improvements | Windows EOL bug is data corruption, higher priority than anchor ambiguity improvements | initial |
 | Don't change MCP tool API signatures | Backward compatibility — agents already know these tool interfaces | initial |
 | Scope out anchor ambiguity improvements | Better error messages are sufficient for now; `match_index` is a follow-up feature | initial |
