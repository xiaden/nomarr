# Task: Cross-File Move Text Support

## Problem Statement

`move_text` currently only supports moving lines within a single file. The most attractive use case—splitting a file into multiple files—requires cross-file moves.

## Current State

```python
def move_text(
    file_path: str,
    source_start: int,
    source_end: int,
    target_line: int,
    workspace_root: Path,
) -> dict:
```

- Reads one file
- Extracts lines from source range
- Inserts at target_line in same file
- Single mtime check, single write

## Target State

```python
def move_text(
    file_path: str,
    source_start: int,
    source_end: int,
    target_line: int,
    workspace_root: Path,
    target_file: str | None = None,  # NEW: defaults to file_path
) -> dict:
```

- If `target_file` is None or same as `file_path`: same-file move (existing behavior)
- If `target_file` differs: cross-file move

## Design Decisions

### D1: Target file doesn't exist
**Decision:** Error. Use `create_file` first.
**Rationale:** Keeps move_text focused on moving, not file creation. Avoids ambiguity about initial content.

### D2: Atomicity across two files
**Decision:** Best-effort. Write target first, then source. If source write fails, target is already modified.
**Rationale:** True two-file atomicity requires transactions we don't have. Writing target first means worst case is duplicated content (recoverable) rather than lost content.

### D3: EOL normalization for cross-file
**Decision:** Normalize extracted lines to target file's EOL style before insertion.
**Rationale:** Mixed EOL styles in a file are worse than a briefly incorrect EOL that gets normalized on next edit.

### D4: mtime checks
**Decision:** Check both files' mtime before writing either. Fail if either changed.
**Rationale:** Prevents partial writes when either file was modified during operation.

## Implementation Plan

### Phase 1: Refactor existing code for clarity
- [x] Remove whole-document EOL normalization (already done)
- [x] Extract `_read_and_validate_source` helper
- [x] Extract `_write_result` helper that doesn't include source_range/target in signature

### Phase 2: Add target_file parameter
- [x] Add `target_file: str | None = None` parameter to function signature
- [x] Update docstring with new parameter and cross-file behavior
- [x] Resolve target_file path (or default to file_path)

### Phase 3: Cross-file logic
- [x] If same file: existing behavior
- [x] If different files:
  - [ ] Read source file with metadata
  - [ ] Read target file with metadata  
  - [ ] Validate source range against source file
  - [ ] Validate target_line against target file
  - [ ] Extract lines from source
  - [ ] Normalize extracted lines to target EOL
  - [ ] Build new source content (lines removed)
  - [ ] Build new target content (lines inserted)
  - [ ] Check both mtimes before writing
  - [ ] Write target file first
  - [ ] Write source file second
  - [ ] Return combined result

### Phase 4: Update MCP registration
- [x] Update tool registration in nomarr_mcp.py to expose target_file parameter

### Phase 5: Test
- [x] Same-file move still works
- [x] Cross-file move works
- [x] Cross-file to non-existent file errors
- [x] Cross-file outside workspace errors
- [x] EOL normalization works (LF source → CRLF target)

## Files to Modify

1. `scripts/mcp/tools/move_text.py` - Main implementation
2. `scripts/mcp/tools/file_helpers.py` - May need `resolve_file_path_for_write` variant that allows non-existent? (No, per D1)
3. `scripts/mcp/nomarr_mcp.py` - Tool registration

## Risks

- **Data loss on partial failure:** Mitigated by write order (target first = duplication not loss)
- **Complexity creep:** Keep same-file path simple, branch early for cross-file
