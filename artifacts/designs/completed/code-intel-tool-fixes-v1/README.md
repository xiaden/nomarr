# Code-Intel MCP Tool Reliability Fixes — Implementation Parts

## Parts

| Part | Title | Depends On | Layers |
|---|---|---|---|
| A | Shared helper fixes (content_boundaries + file_helpers) | None | helpers |
| B | Insert text EOL + trailing newline fix | A | tools (edit_file_insert_text) |
| C | Python navigation tool fixes | None | tools (read_module_source, locate_module_symbol) |

## Dependency Graph

```
A (helpers)          C (python nav)
    |                    |
    v                    |
B (insert text)          |
                         |
(no cross-deps between B and C)
```

## Execution Rounds

Round 1: A, C (no mutual deps — A is helpers, C is independent tools)
Round 2: B (depends on A's helper changes)

## Per-Part Scope

### Part A: Shared helper fixes (content_boundaries + file_helpers)

Fixes the foundation that all 3 content-boundary tools depend on. In `content_boundaries.py`: add ±2 tolerance to `expected_line_count` with a warning when tolerance is used (not exact match). In `file_helpers.py`: convert tab rejection from hard error to warning metadata (tool still works, but response includes a warning). Tests for both changes. After this part, `edit_file_move_by_content` and `edit_file_replace_by_content` benefit automatically — no tool-level changes needed.

### Part B: Insert text EOL + trailing newline fix

Fixes the `edit_file_insert_text.py` tool's Windows EOL bug (`content.split("\n")` → `splitlines()`) and the trailing newline stripping that silently drops intentional blank lines. Tests covering CRLF files and multi-newline content insertion.

### Part C: Python navigation tool fixes

Independent from content-boundary work. In `locate_module_symbol.py`: fix parent_filter gap (exclude top-level functions from parent-scoped queries), use path-segment matching instead of substring. In `read_module_source.py`: support 3+ levels of AST nesting in `_find_symbol_in_ast()`. Tests for all fixes. These tools already receive `workspace_root` via the config system from server.py's ROOT, so the CWD issue is only a concern at server startup (out of scope).
