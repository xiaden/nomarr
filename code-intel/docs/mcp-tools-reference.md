# MCP File Mutation Tools Reference

## Overview

The nomarr-dev MCP server provides 4 atomic file mutation tools designed for bulk editing operations. All tools follow these principles:

- **Batch-first APIs**: All tools accept arrays for atomic multi-file operations
- **Atomic transactions**: All-or-nothing execution with complete rollback on any failure
- **Context as validation**: Return changed regions with context (±2 lines) to eliminate verification reads
- **Coordinate space rule**: For same-file operations, all coordinates refer to ORIGINAL file state; applied bottom-to-top
- **Type safety**: Pydantic models enforce validation before execution

---

## file_create_new

**Purpose**: Create new files atomically with automatic directory creation.

**Function signature:**
```python
def file_create_new(ops: list[dict]) -> dict
```

### CreateOp Model

```python
{
    "path": str,          # File path to create (workspace-relative or absolute)
    "content": str = ""   # Initial content (default: empty string)
}
```

### Behavior

- **Automatic directory creation**: Parent directories created automatically (mkdir -p)
- **Fails on existing files**: Returns error if any target file already exists
- **Atomicity**: All files created or none (complete rollback on any failure)
- **Duplicate detection**: Fails if same path appears multiple times in batch
- **Context return**: First ~52 lines of each created file with line numbers

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\Github\\nomarr\\services\\auth_svc.py",
            "start_line": 1,
            "end_line": 10,
            "new_context": [
                "1: # Authentication Service",
                "2: ",
                "3: class AuthService:",
                "4:     def __init__(self):",
                "5:         pass"
            ],
            "bytes_written": 1234
        }
    ],
    "failed_ops": []
}
```

### Response (failure)

```python
{
    "status": "failed",
    "applied_ops": [],
    "failed_ops": [
        {
            "index": 0,
            "filepath": "d:\\Github\\nomarr\\services\\existing.py",
            "reason": "File already exists"
        }
    ]
}
```

### Examples

**Example 1: Create single file**
```python
file_create_new([
    {"path": "services/auth_svc.py", "content": "# New auth service\n"}
])
```

**Example 2: Create batch with nested directories**
```python
file_create_new([
    {"path": "services/auth/session_svc.py", "content": "# Session service\n"},
    {"path": "services/auth/token_svc.py", "content": "# Token service\n"},
    {"path": "services/auth/__init__.py", "content": ""}
])
```

**Example 3: Create empty configuration files**
```python
file_create_new([
    {"path": "config/dev.yaml"},
    {"path": "config/prod.yaml"}
])
```

### Common Gotchas

- **No overwrite**: Tool fails if file exists. Use `file_replace` to overwrite.
- **Path resolution**: Workspace-relative paths resolved automatically. Use `\\` on Windows, `/` on Unix.
- **Large files**: Context capped at ~52 lines to prevent payload bloat. Read separately if needed.

---

## file_replace

**Purpose**: Replace entire file contents atomically.

**Function signature:**
```python
def file_replace(ops: list[dict]) -> dict
```

### ReplaceOp Model

```python
{
    "path": str,      # File path to replace (workspace-relative or absolute)
    "content": str    # New file content (replaces entire file)
}
```

### Behavior

- **Fails on missing files**: Returns error if any target file doesn't exist
- **Whole-file replacement**: Overwrites entire file contents
- **Atomicity**: All files replaced or none (original content restored on failure)
- **Duplicate detection**: Fails if same path appears multiple times in batch
- **Context capping**: Returns first 2 + last 2 lines (not entire file) to prevent payload bloat
- **Context return**: Includes `lines_total` and `bytes_written` for verification

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\Github\\nomarr\\config.py",
            "start_line": 1,
            "end_line": 100,
            "lines_total": 100,
            "new_context": [
                "1: # Configuration",
                "2: DEBUG = True",
                "...",
                "99: # End config",
                "100: "
            ],
            "bytes_written": 5678
        }
    ],
    "failed_ops": []
}
```

### Response (failure)

```python
{
    "status": "failed",
    "applied_ops": [],
    "failed_ops": [
        {
            "index": 1,
            "filepath": "d:\\Github\\nomarr\\missing.py",
            "reason": "File not found"
        }
    ]
}
```

### Examples

**Example 1: Replace configuration file**
```python
file_replace([
    {"path": "config.yaml", "content": "debug: true\nport: 8000\n"}
])
```

**Example 2: Batch replace service implementations**
```python
file_replace([
    {"path": "services/auth_svc.py", "content": "# Refactored auth service\n..."},
    {"path": "services/user_svc.py", "content": "# Refactored user service\n..."}
])
```

**Example 3: Empty file (clear contents)**
```python
file_replace([
    {"path": "temp.log", "content": ""}
])
```

### Common Gotchas

- **No creation**: Tool fails if file doesn't exist. Use `file_create_new` to create.
- **Context capping**: Large files return truncated context (first 2 + last 2 lines). Use `lines_total` to verify.
- **Atomic rollback**: Original content restored on any failure (disk full, permissions, etc.).

---

## file_insert_text

**Purpose**: Insert text at specific positions without string matching.

**Function signature:**
```python
def file_insert_text(ops: list[dict]) -> dict
```

### InsertOp Model

```python
{
    "path": str,                            # File path (workspace-relative or absolute)
    "content": str,                         # Content to insert
    "at": "bof|eof|before_line|after_line", # Insertion mode
    "line": int | None = None,              # Line number (1-indexed, required for before/after_line)
    "col": int | None = None                # Column position (0-indexed, optional)
}
```

**Column positioning:**
- `None` = Beginning of line (BOL)
- `0` = Beginning of line (BOL)
- `-1` = End of line (EOL)
- `N` = Character position N (0-indexed)

### Behavior

- **All files must exist**: Fails if any target file doesn't exist
- **Four insertion modes**:
  - `bof`: Insert at beginning of file
  - `eof`: Insert at end of file
  - `before_line`: Insert before specified line
  - `after_line`: Insert after specified line
- **Line-only mode** (col=None): Inserts content as new line(s)
- **Row+col mode**: Inserts at exact character position
- **Coordinate space rule**: For same-file ops, all coordinates refer to ORIGINAL file state
- **Bottom-to-top application**: Operations sorted and applied in descending order to preserve coordinates
- **Context return**: Changed region (inserted lines) ± 2 lines in post-change coordinate space

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\Github\\nomarr\\services\\user_svc.py",
            "start_line": 3,
            "end_line": 5,
            "new_context": [
                "1: class UserService:",
                "2:     \"\"\"User management service.\"\"\"",
                "3:     ",
                "4:     def __init__(self, db: Database):",
                "5:         self.db = db",
                "6:     ",
                "7:     def get_user(self, user_id: str):"
            ],
            "bytes_written": 234
        }
    ],
    "failed_ops": []
}
```

### Examples

**Example 1: Add import at top of file (bof)**
```python
file_insert_text([
    {"path": "services/auth_svc.py", "content": "from datetime import datetime\n", "at": "bof"}
])
```

**Example 2: Add function at end of file (eof)**
```python
file_insert_text([
    {"path": "helpers/utils.py", "content": "\n\ndef cleanup():\n    pass\n", "at": "eof"}
])
```

**Example 3: Insert comment before function (before_line)**
```python
file_insert_text([
    {"path": "services/user_svc.py", "content": "    # TODO: Add caching\n", "at": "before_line", "line": 45}
])
```

**Example 4: Add decorator after docstring (after_line)**
```python
file_insert_text([
    {"path": "services/auth_svc.py", "content": "    @trace\n", "at": "after_line", "line": 12}
])
```

**Example 5: Character-precise insertion (row+col)**
```python
file_insert_text([
    {"path": "config.py", "content": " | None", "at": "after_line", "line": 10, "col": 15}
])
# Inserts " | None" at line 10, character position 15
```

**Example 6: Batch same-file inserts (coordinate preservation)**
```python
file_insert_text([
    {"path": "service.py", "content": "# Comment 1\n", "at": "after_line", "line": 10},
    {"path": "service.py", "content": "# Comment 2\n", "at": "after_line", "line": 20},
    {"path": "service.py", "content": "# Comment 3\n", "at": "after_line", "line": 30}
])
# All line numbers (10, 20, 30) refer to ORIGINAL file state
# Tool applies bottom-to-top automatically
```

### Common Gotchas

- **No file creation**: Tool fails if file doesn't exist. Use `file_create_new` first.
- **Coordinate space**: For same-file batches, all line numbers refer to ORIGINAL file. Don't adjust for previous insertions.
- **Line validation**: `before_line` and `after_line` require `line` parameter. Validator enforces this.
- **Col positioning**: `-1` means EOL (common for appending to lines). `None` or `0` means BOL.

---

## file_copy_paste_text

**Purpose**: Copy text from sources and paste to targets atomically (batch boilerplate duplication).

**Function signature:**
```python
def file_copy_paste_text(ops: list[dict]) -> dict
```

### CopyPasteOp Model

```python
{
    "source_path": str,                        # Source file path
    "source_start_line": int,                  # Source start line (1-indexed, inclusive)
    "source_start_col": int | None = None,     # Source start col (0-indexed, None=BOL)
    "source_end_line": int,                    # Source end line (1-indexed, inclusive)
    "source_end_col": int | None = None,       # Source end col (0-indexed, None/−1=EOL)
    "target_path": str,                        # Target file path
    "target_line": int,                        # Target line (1-indexed, -1=EOF)
    "target_col": int | None = None            # Target col (0-indexed, None=BOL, -1=EOL)
}
```

**Column positioning:**
- Source col: `None` = BOL, `0` = BOL, `-1` = EOL, `N` = char N
- Target col: `None` = BOL, `0` = BOL, `-1` = EOL, `N` = char N

### Behavior

- **Source files read-only**: Never modified, only read
- **All files must exist**: Fails if any source or target file doesn't exist (no creation)
- **Pure insertion**: No overwrite/replace semantics, only insertion
- **Source text caching**: Each unique source range read once, cached for multiple paste operations
- **Line-only mode** (all col=None): Copy full lines, insert as new lines
- **Row+col mode**: Character-precise copy/paste
- **Coordinate space rule**: For same-file targets, all coordinates refer to ORIGINAL file state
- **Bottom-to-top application**: Operations grouped by target file, applied in descending order
- **Context return**: Changed region (pasted lines) ± 2 lines at target location

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\Github\\nomarr\\services\\auth_svc.py",
            "start_line": 15,
            "end_line": 17,
            "new_context": [
                "13:     def login(self, username: str):",
                "14:         \"\"\"Login user.\"\"\"",
                "15:         @trace",
                "16:         @cache",
                "17:         ",
                "18:         # Authenticate",
                "19:         user = self.db.get_user(username)"
            ],
            "bytes_written": 145
        }
    ],
    "failed_ops": []
}
```

### Examples

**Example 1: Copy boilerplate to multiple locations**
```python
file_copy_paste_text([
    # Copy error handling pattern from helpers.py lines 5-7
    {"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
     "target_path": "services/auth_svc.py", "target_line": 10},
    {"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
     "target_path": "services/auth_svc.py", "target_line": 25},
    {"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
     "target_path": "services/user_svc.py", "target_line": 15},
])
# helpers.py read ONCE, cached, pasted to all targets
```

**Example 2: Copy function signature (line-only mode)**
```python
file_copy_paste_text([
    {"source_path": "services/auth_svc.py", "source_start_line": 20, "source_end_line": 22,
     "target_path": "services/user_svc.py", "target_line": 30}
])
```

**Example 3: Copy partial line (character-precise)**
```python
file_copy_paste_text([
    {"source_path": "models.py", "source_start_line": 10, "source_start_col": 15,
     "source_end_line": 10, "source_end_col": 30,
     "target_path": "schemas.py", "target_line": 5, "target_col": 20}
])
```

**Example 4: Duplicate code block within same file**
```python
file_copy_paste_text([
    {"source_path": "service.py", "source_start_line": 10, "source_end_line": 15,
     "target_path": "service.py", "target_line": 30},
    {"source_path": "service.py", "source_start_line": 10, "source_end_line": 15,
     "target_path": "service.py", "target_line": 50}
])
# Line 30 and 50 refer to ORIGINAL file state
# Source range (10-15) cached once
```

### Common Gotchas

- **No file creation**: Both source and target must exist. Use `file_create_new` first if needed.
- **Caching optimization**: Duplicate source ranges read only once. Use this for batch boilerplate duplication.
- **Coordinate space**: For same-file targets, all target_line values refer to ORIGINAL file state.
- **Pure insertion**: No overwrite semantics. Use `file_replace` if you need to replace content.
- **Source immutability**: Source files never modified, even if same as target.

---

## Atomicity Guarantees

All tools enforce atomic transactions:

1. **Pre-flight validation**: All paths resolved, all validations passed before ANY file modifications
2. **Staging**: Changes staged in memory or temp files
3. **Atomic commit**: All changes written atomically (rename-based)
4. **Complete rollback**: Any failure triggers complete rollback (all files restored to original state)
5. **No partial success**: Tools return `status: "failed"` with empty `applied_ops` on any error

**Example rollback scenario:**
```python
file_replace([
    {"path": "file1.py", "content": "new content 1"},
    {"path": "file2.py", "content": "new content 2"},
    {"path": "missing.py", "content": "new content 3"}  # Doesn't exist
])
# Result: ALL operations rolled back (file1.py and file2.py unchanged)
# Response: status="failed", applied_ops=[], failed_ops=[{index: 2, reason: "File not found"}]
```

---

## Coordinate Space Rule

**Critical**: For same-file batch operations, all coordinates refer to ORIGINAL file state.

**Why?** Prevents coordinate drift when multiple insertions affect same file.

**Implementation:** Tools group operations by target file and apply bottom-to-top (descending line order).

**Example:**
```python
# Original file (lines 1-100)
file_insert_text([
    {"path": "service.py", "content": "# Comment A\n", "at": "after_line", "line": 10},
    {"path": "service.py", "content": "# Comment B\n", "at": "after_line", "line": 50},
    {"path": "service.py", "content": "# Comment C\n", "at": "after_line", "line": 90}
])
# DON'T adjust line numbers: 10, 50, 90 all refer to ORIGINAL state
# Tool applies in order: line 90 → line 50 → line 10 (bottom-to-top)
```

---

## Usage Patterns

### Pattern 1: Extract Functions to New Files

```python
# Step 1: Create target files
file_create_new([
    {"path": "services/auth/session.py", "content": "# Session management\n"},
    {"path": "services/auth/token.py", "content": "# Token management\n"}
])

# Step 2: Copy functions to new files
file_copy_paste_text([
    {"source_path": "services/auth_svc.py", "source_start_line": 45, "source_end_line": 67,
     "target_path": "services/auth/session.py", "target_line": -1},  # EOF
    {"source_path": "services/auth_svc.py", "source_start_line": 100, "source_end_line": 125,
     "target_path": "services/auth/token.py", "target_line": -1}
])

# Step 3: Delete originals (use edit_move_text or manual deletion)
```

### Pattern 2: Batch Boilerplate Duplication

```python
# Copy error handling boilerplate to multiple service methods
ops = []
for service_file, line_numbers in boilerplate_targets.items():
    for line in line_numbers:
        ops.append({
            "source_path": "helpers/error_handling.py",
            "source_start_line": 10,
            "source_end_line": 12,
            "target_path": service_file,
            "target_line": line
        })

file_copy_paste_text(ops)
# helpers/error_handling.py read ONCE, cached for all pastes
```

### Pattern 3: Batch Configuration Updates

```python
# Replace all environment configs atomically
file_replace([
    {"path": "config/dev.yaml", "content": "debug: true\nport: 8000\n"},
    {"path": "config/staging.yaml", "content": "debug: false\nport: 8001\n"},
    {"path": "config/prod.yaml", "content": "debug: false\nport: 443\n"}
])
```

### Pattern 4: Add Imports and Type Hints (Same File)

```python
# Add import at top and type hint at specific function
file_insert_text([
    {"path": "services/user_svc.py", "content": "from typing import Optional\n", "at": "bof"},
    {"path": "services/user_svc.py", "content": " | None", "at": "after_line", "line": 45, "col": 25}
])
# Line 45, col 25 refers to ORIGINAL file (before import added)
```

---

## Error Handling

All tools return structured error responses:

```python
{
    "status": "failed",
    "applied_ops": [],  # Always empty on failure
    "failed_ops": [
        {
            "index": 2,
            "filepath": "d:\\Github\\nomarr\\missing.py",
            "reason": "File not found"
        }
    ]
}
```

**Common error reasons:**
- `"File already exists"` (file_create_new)
- `"File not found"` (file_replace, file_insert_text, file_copy_paste_text)
- `"Duplicate path in batch"` (all tools)
- `"Invalid line number"` (file_insert_text, file_copy_paste_text)
- `"Invalid column position"` (file_insert_text, file_copy_paste_text)
- `"Permission denied"` (all tools)
- `"Disk full"` (all tools)

**Error recovery:**
1. All operations rolled back automatically
2. No manual cleanup required
3. Check `failed_ops` for specific error details
4. Fix issues and retry entire batch

---

## Performance Considerations

### Source Caching (file_copy_paste_text)

```python
# EFFICIENT: Source read once
file_copy_paste_text([
    {"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
     "target_path": "file1.py", "target_line": 10},
    {"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
     "target_path": "file2.py", "target_line": 20}
])
# helpers.py lines 5-7 cached after first read

# INEFFICIENT: Multiple tool calls
file_copy_paste_text([{"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
                       "target_path": "file1.py", "target_line": 10}])
file_copy_paste_text([{"source_path": "helpers.py", "source_start_line": 5, "source_end_line": 7,
                       "target_path": "file2.py", "target_line": 20}])
# helpers.py read twice (no caching across calls)
```

### Batch Operations

Always prefer single batch call over multiple sequential calls:
- **Better atomicity** (all-or-nothing vs partial failures)
- **Better performance** (single validation phase, single I/O transaction)
- **Better caching** (for file_copy_paste_text)

### Context Return Size

Tools limit context return to prevent payload bloat:
- `file_create_new`: ~52 lines
- `file_replace`: First 2 + last 2 lines
- `file_insert_text`: Changed region ± 2 lines
- `file_copy_paste_text`: Changed region ± 2 lines

If you need full file contents, read separately after mutation.

---

## Choosing the Right Tool

| Scenario | Tool | Why |
|----------|------|-----|
| Create new files | `file_create_new` | Auto-creates directories, fails on existing files |
| Replace entire file | `file_replace` | Atomic whole-file replacement with capped context |
| Add import at top | `file_insert_text` (at="bof") | Precise positioning without string matching |
| Add function at end | `file_insert_text` (at="eof") | Direct EOF insertion |
| Insert at specific line | `file_insert_text` (at="before/after_line") | Line-number targeting |
| Copy boilerplate code | `file_copy_paste_text` | Source caching optimizes reads |
| Duplicate code block | `file_copy_paste_text` | Preserves exact formatting |
| Move code between files | `edit_move_text` | Extraction + deletion in one operation |

---

## Related Tools

- **edit_move_text**: Move/extract text between files (creates target if missing)
- **atomic_replace**: Single-file string replacement (for targeted edits)
- **module_get_source**: Read function/class source (for understanding before editing)
- **lint_backend**: Validate changes (ALWAYS run after Python file mutations)
