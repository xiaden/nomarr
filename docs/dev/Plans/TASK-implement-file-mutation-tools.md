# Task: Implement File Mutation MCP Tools

## Problem Statement

Nomarr-dev MCP server needs 4 new file mutation tools to complete editing capabilities:
1. `file_create_new` - Create new files (fail if exists)
2. `file_replace` - Replace entire file contents (fail if missing)
3. `file_insert_text` - Insert at specific line/col without string matching
4. `file_copy_paste_text` - Copy text between locations (exact duplication)

Plus extend `edit_move_text` to support target file creation.

**Design Principles:**
- Creation and replacement are disjoint (no mega-tools)
- Batch-first APIs (all tools accept arrays)
- Atomic transactions (all-or-nothing, never best-effort)
- Context as validation (return changed region ±2 lines)
- Coordinate space rule: all coordinates in batch refer to ORIGINAL file state

**Path conventions:**
- Tools go in `scripts/mcp/tools/`
- Helpers go in `scripts/mcp/tools/helpers/`
- Response models go in `scripts/mcp/tools/helpers/`

## Phases

### Phase 1: Shared Infrastructure and Response Models
- [ ] Implement scripts/mcp/tools/helpers/response_models.py with BatchResponse, AppliedOp, FailedOp models and custom exceptions (FileOperationError, BatchOperationError, ValidationError, ConflictError)
- [ ] Extend scripts/mcp/tools/helpers/file_helpers.py with path resolution (resolve_path, resolve_path_for_create), validation (validate_line_range, validate_col), context extraction (extract_context, format_context_with_line_numbers), atomic writes (atomic_write), and batch helpers (group_ops_by_file, sort_ops_for_application with descending=True)
- [ ] Verify all helpers pass lint_backend with zero errors and cover atomicity, rollback scenarios, and edge cases (empty files, large files, invalid paths)

### Phase 2: Atomic File Creation
- [ ] Implement scripts/mcp/tools/file_create_new.py with CreateOp model (path, content="") and batch validation (resolve paths, check none exist, detect duplicates)
- [ ] Implement atomic staging and commit with parent dir creation, temp file writes, and atomic rename with rollback on any failure
- [ ] Add error handling for FileExistsError, PermissionError, and disk space errors with proper rollback and context extraction (first ~52 lines with line numbers)
- [ ] Add docstring documenting CreateOp fields, batch behavior, atomicity guarantees, failure modes, and mkdir -p behavior with 2-3 examples
- [ ] Verify file_create_new handles: single/batch creation, nested dirs, FileExistsError on conflict, complete rollback on partial failure, empty files, and lint_backend passes

### Phase 3: Atomic File Replacement
- [ ] Implement scripts/mcp/tools/file_replace.py with ReplaceOp model (path, content) and batch validation (resolve paths, check all exist, detect duplicates)
- [ ] Implement atomic staging and commit with original backups, temp file writes, and atomic rename with rollback to restore backups on any failure
- [ ] Add error handling for FileNotFoundError, PermissionError, and disk space errors with context extraction (first 2 + last 2 lines with line numbers and lines_total)
- [ ] Add docstring documenting ReplaceOp fields, whole-file replacement semantics, context capping strategy, atomicity guarantees, and failure modes with 2-3 examples
- [ ] Verify file_replace handles: single/batch replacement, FileNotFoundError on missing files, complete rollback on partial failure, empty content, large files, and lint_backend passes

### Phase 4: Positional Text Insertion
- [ ] Implement scripts/mcp/tools/file_insert_text.py with InsertOp model (path, content, at="bof|eof|before_line|after_line", line=None, col=None) and field validator requiring line for before_line/after_line modes
- [ ] Implement batch validation (resolve paths, check all exist, validate at+line combos, validate col if specified) and grouping/sorting (group by filepath, sort descending for bottom-to-top application)
- [ ] Implement all insertion modes (bof, eof, before_line, after_line) with character-precise col positioning and atomic write via temp files
- [ ] Add error handling for FileNotFoundError and ValueError (invalid line/col) with context extraction (changed region ± 2 lines with line numbers in post-change coordinate space)
- [ ] Add docstring documenting InsertOp fields, all 4 insertion modes, line-only vs row+col behavior, coordinate space rule for same-file batches, and bottom-to-top application strategy with examples for each mode
- [ ] Verify file_insert_text handles: bof/eof/before_line/after_line modes, col positioning (None/0/-1/N), batch same-file ops with coordinate preservation, batch multi-file ops, edge cases (line 1, EOF, invalid coords), and lint_backend passes

### Phase 5: Cross-File Move with Auto-Creation
- [ ] Extend scripts/mcp/tools/edit_move_text.py to check target file existence and auto-create missing targets (parent dirs + empty file) with target_created flag and mtime check skip for new files
- [ ] Add target_filepath, target_created boolean, and warnings array to AppliedOp response with "Created new file" message when applicable
- [ ] Update docstring with extraction-to-new-file example and document auto-creation behavior, target_created flag, and warning messages
- [ ] Verify edit_move_text handles: move to existing file, move to new file (nested paths), batch moves creating multiple targets, warnings appear correctly, and lint_backend passes

### Phase 6: Batch Copy-Paste Operations
- [ ] Implement scripts/mcp/tools/file_copy_paste_text.py with CopyPasteOp model (source_path, source_start_line, source_start_col, source_end_line, source_end_col, target_path, target_line, target_col) and field validator (source_end_line >= source_start_line)
- [ ] Implement _extract_source_text and _insert_at_target helpers supporting both line-only and row+col modes with proper EOL/BOL handling
- [ ] Implement 6-phase execution: (1) validate all source/target paths, (2) cache source text (read once per unique range), (3) group ops by target file, (4) apply insertions bottom-to-top per target, (5) atomic write all modified files, (6) build BatchResponse with context (changed region ± 2 lines)
- [ ] Add error handling for FileNotFoundError and ValueError (invalid ranges) and ensure target files are never created (fail if missing)
- [ ] Add docstring documenting CopyPasteOp fields, caching strategy, coordinate space rule, line-only vs row+col modes, and "stamp decorator 50 times" use case with 2-3 examples
- [ ] Verify file_copy_paste_text handles: line-only copy, char-precise copy, stamp 50x same source to multiple targets, same-file targets with coordinate preservation, multi-source batches, caching eliminates redundant reads, FileNotFoundError on missing target, and lint_backend passes

### Phase 7: MCP Server Integration
- [ ] Register all 4 new tools (file_create_new, file_replace, file_insert_text, file_copy_paste_text) in MCP server (scripts/mcp/server.py or config)
- [ ] Verify tool discovery and invocation via MCP client for all 4 tools with simple test operations

### Phase 8: Documentation and Guidelines
- [ ] Update .github/copilot-instructions.md tool hierarchy section with "when to use each tool" guidance (create vs replace vs insert vs copy/paste), coordinate space rule for same-file batches, and "stamp decorator 50 times" example
- [ ] Create docs/dev/mcp-tools-reference.md documenting all 4 tool APIs (CreateOp, ReplaceOp, InsertOp, CopyPasteOp), behaviors, caching strategy, atomicity guarantees, usage patterns, common gotchas, and 2-3 examples per tool
- [ ] Update MCP server README with new file mutation capabilities and link to mcp-tools-reference.md

### Phase 9: Test Coverage and Validation
- [ ] Create tests/mcp/test_file_create_new.py verifying: single/batch creation, nested dirs, FileExistsError on conflict, complete rollback on partial failure, empty files, large files (>1MB)
- [ ] Create tests/mcp/test_file_replace.py verifying: single/batch replacement, FileNotFoundError on missing files, complete rollback on partial failure, empty content, large files, binary files
- [ ] Create tests/mcp/test_file_insert_text.py verifying: bof/eof/before_line/after_line modes, col positioning (None/0/-1/N), batch same-file ops with coordinate preservation, batch multi-file ops, edge cases (line 1, EOF, invalid coords)
- [ ] Create tests/mcp/test_file_copy_paste_text.py verifying: line-only copy, char-precise copy, stamp 50x decorator pattern, same-file targets, multi-source batches, caching eliminates redundant reads, FileNotFoundError on missing target
- [ ] Create tests/mcp/test_edit_move_text_extended.py verifying: move to existing file, move to new file (nested paths), batch moves creating multiple targets, warnings appear correctly
- [ ] Create tests/mcp/test_batch_atomicity.py verifying cross-tool atomic transaction scenarios and rollback behavior
- [ ] Create integration test for full refactor workflow (extract 16 functions to new files using file_copy_paste_text + edit_move_text)
- [ ] Run all tests with pytest and verify >90% code coverage for all new tools

## Completion Criteria

- All 4 new tools (file_create_new, file_replace, file_insert_text, file_copy_paste_text) implemented and pass lint_backend with zero errors
- All tools registered in MCP server and discoverable/callable via MCP client
- copilot-instructions.md updated with tool hierarchy and usage guidance
- mcp-tools-reference.md created with complete API documentation and examples
- Test suite achieves >90% code coverage with all tests passing
- Integration test demonstrates full refactor workflow (extract to 16 new files)
- All tools enforce atomicity (all-or-nothing, complete rollback on any failure)
- Context validation eliminates need for separate read operations (changed region ± 2 lines returned)
- Coordinate space rule enforced and documented (all batch coordinates refer to original file state, applied bottom-to-top)

---

## Tool Specifications

### file_create_new

**Function signature:**
```python
def file_create_new(ops: list[dict]) -> dict
```

**CreateOp:**
```python
{
    "path": str,          # File path to create
    "content": str = ""   # Initial content (default: empty)
}
```

**Behavior:**
- Creates parent directories automatically (mkdir -p always on)
- Fails if any target file already exists
- Atomic: all files created or none

**Response (success):**
```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "/absolute/path/to/file.py",
            "start_line": 1,
            "end_line": 10,
            "new_context": [
                "1: # New service",
                "2: ",
                "3: def main():",
                "..."
            ],
            "bytes_written": 1234
        }
    ],
    "failed_ops": []
}
```

**Response (failure):**
```python
{
    "status": "failed",
    "applied_ops": [],
    "failed_ops": [
        {
            "index": 2,
            "filepath": "services/existing.py",
            "reason": "File already exists"
        }
    ]
}
```

### file_replace

**Function signature:**
```python
def file_replace(ops: list[dict]) -> dict
```

**ReplaceOp:**
```python
{
    "path": str,      # File path to replace
    "content": str    # New file content (replaces entire file)
}
```

**Behavior:**
- Fails if any target file doesn't exist
- Overwrites entire file contents
- Atomic: all files replaced or none

**Context return for whole-file replacement:**
- First 2 lines + last 2 lines (not entire file)
- Include `bytes_written` and `lines_total`

### file_insert_text

**Function signature:**
```python
def file_insert_text(ops: list[dict]) -> dict
```

**InsertOp:**
```python
{
    "path": str,
    "content": str,
    "at": "bof" | "eof" | "before_line" | "after_line",
    "line": int | None = None,  # Required for before/after_line
    "col": int | None = None    # Optional: None=BOL, 0=BOL, -1=EOL, N=char N
}
```

**Behavior:**
- All target files must exist
- Line-only mode (col=None): Inserts content as new line(s)
- Row+col mode: Inserts at exact character position
- For same-file ops: all coordinates refer to ORIGINAL file state
- Apply operations bottom-to-top to avoid coordinate drift

**Context return:**
- Changed region (inserted lines) ± 2 lines of context
- With line numbers in post-change coordinate space

### file_copy_paste_text

**Function signature:**
```python
def file_copy_paste_text(ops: list[dict]) -> dict
```

**CopyPasteOp:**
```python
{
    "source_path": str,
    "source_start_line": int,               # 1-indexed, inclusive
    "source_start_col": int | None = None,  # 0-indexed, None=BOL
    "source_end_line": int,                 # 1-indexed, inclusive
    "source_end_col": int | None = None,    # 0-indexed, None=EOL, -1=EOL
    "target_path": str,
    "target_line": int,                     # 1-indexed, -1=EOF
    "target_col": int | None = None         # 0-indexed, None=BOL, -1=EOL
}
```

**Behavior:**
- Source files must exist (read-only, never modified)
- Target files must exist (fail if missing, no creation)
- Pure insertion only (no overwrite/replace semantics)
- Line-only mode (all col=None): Copy full lines, insert as new lines
- Row+col mode: Character-precise copy/paste
- Source text cached (read once per unique source range)
- For same-file targets: coordinates refer to ORIGINAL state

**Context return:**
- Changed region (pasted lines) ± 2 lines at target location

**Primary use case:**
"Stamp decorator 50 times across different files" - copy same source range to 50 different target locations in a single atomic batch operation.

### edit_move_text (extension)

**New behavior:**
When target file doesn't exist:
- Create it automatically (empty file)
- Return warning in response
- Set target_created: true in applied_op result

**Response with target creation:**
```python
{
    "index": 0,
    "filepath": "main.py",
    "target_filepath": "utils.py",  # NEW
    "target_created": true,          # NEW
    "start_line": 1,
    "end_line": 15,
    "new_context": [...],
    "warnings": [                    # NEW
        "Created new file: utils.py"
    ]
}
```

---

## Design Decisions

1. **No mtime validation** - Operations fast enough (milliseconds) that race conditions with user edits are negligible. Adds overhead for theoretical problem.

2. **No extension check for new files** - Models aren't that error-prone, and typos self-correct quickly (import will fail). YAGNI.

3. **Context = validation** - Return changed region ±2 lines instead of requiring separate read. Eliminates verify step.

4. **file_copy_paste_text no file creation** - Keeps tool focused. Creation would make it a "do anything" mega-tool.

5. **edit_move_text creates targets by default** - Optimizes for "extract to 16 new files" use case. Warning + target_created flag make it auditable.

6. **Batch-first APIs** - Every tool takes arrays. Prevents N tool calls for N ops, improves atomicity.

7. **Coordinate space: original file state** - All line numbers in batch refer to pre-operation state. Applied bottom-to-top to avoid drift.

8. **file_replace caps context** - Returns first 2 + last 2 lines, not entire file. Prevents payload bloat.

9. **Line numbering: 1-indexed** - Matches editor conventions and linter output.

10. **Col numbering: 0-indexed** - Matches string indexing conventions.

---

## Notes

**Why separate copy/paste from insert:** Copy/paste reads from source files (complex caching logic), insert creates content from scratch. Combining would create mega-tool violating single-responsibility.

**Implementation patterns:**
- Follow file_insert_text for grouping/sorting logic
- Follow file_create_new/file_replace for atomic writes with rollback
- Use shared helpers from Phase 1 infrastructure

**This plan replaces ad-hoc file editing patterns with principled, atomic tools. Completes nomarr-dev MCP server's core editing capabilities. With these tools + existing semantic tools, agent is ~95% self-sufficient for nomarr development.**
