# Coding Tools MCP File Editing Reference

## Overview

The `coding-tools` MCP server exposes 8 file editing tools. This reference focuses on the create, replace, and insert primitives that form the core editing surface:

- `edit_file_create`
- `edit_file_replace_content`
- `edit_file_insert_at_boundary`
- `edit_file_insert_at_line`

Related targeted-edit tools are covered in the guidance tables at the end of this document: `edit_file_replace_string`, `edit_file_replace_by_content`, `edit_file_move`, and `edit_file_move_by_content`.

All editing tools follow these principles:

- **Batch-first APIs**: Create, replace, and insert tools accept lists for atomic multi-file operations
- **Atomic transactions**: All-or-nothing execution with complete rollback on any failure
- **Context as validation**: Return changed regions with nearby context so callers can validate without extra reads
- **Content-aware targeting**: Boundary- and anchor-based edits avoid brittle line-number arithmetic
- **Type safety**: Pydantic models validate structured arguments before execution

---

## edit_file_create

**Purpose**: Create new files atomically with automatic directory creation.

**Function signature:**

```python
def edit_file_create(files: list[dict]) -> dict
```

### CreateOp Model

```python
{
    "path": str,          # File path to create (workspace-relative or absolute)
    "content": str = ""   # Initial content (default: empty string)
}
```

### Behavior

- **Automatic directory creation**: Parent directories are created automatically
- **Fails on existing files**: Returns an error if any target file already exists
- **Atomicity**: All files are created or none are created
- **Duplicate detection**: Fails if the same path appears multiple times in the batch
- **Context return**: Returns the opening lines of each created file with line numbers

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\workspace\\sample-app\\services\\example_service.py",
            "start_line": 1,
            "end_line": 6,
            "new_context": [
                "1: # Example service",
                "2: ",
                "3: class ExampleService:",
                "4:     def run(self) -> None:",
                "5:         pass"
            ],
            "bytes_written": 96
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
            "filepath": "d:\\workspace\\sample-app\\services\\existing.py",
            "reason": "File already exists"
        }
    ]
}
```

### Examples

**Example 1: Create a single file**

```python
edit_file_create(files=[
    {"path": "services/example_service.py", "content": "# Example service\n"}
])
```

**Example 2: Create a nested batch**

```python
edit_file_create(files=[
    {"path": "services/example/session_service.py", "content": "# Session service\n"},
    {"path": "services/example/token_service.py", "content": "# Token service\n"},
    {"path": "services/example/__init__.py", "content": ""}
])
```

**Example 3: Create empty configuration files**

```python
edit_file_create(files=[
    {"path": "config/dev.yaml"},
    {"path": "config/prod.yaml"}
])
```

### Common Gotchas

- **No overwrite**: The tool fails if the file already exists. Use `edit_file_replace_content` to overwrite an existing file.
- **Path resolution**: Workspace-relative paths are resolved automatically. Absolute paths are also supported.
- **Large files**: Returned context is capped. Read the file separately if you need the full content.

---

## edit_file_replace_content

**Purpose**: Replace entire file contents atomically.

**Function signature:**

```python
def edit_file_replace_content(ops: list[dict]) -> dict
```

### ReplaceOp Model

```python
{
    "path": str,      # File path to replace (workspace-relative or absolute)
    "content": str    # New file content (replaces the entire file)
}
```

### Behavior

- **Fails on missing files**: Returns an error if any target file does not exist
- **Whole-file replacement**: Overwrites the entire file contents
- **Atomicity**: All files are replaced or all changes are rolled back
- **Duplicate detection**: Fails if the same path appears multiple times in the batch
- **Context capping**: Returns summarized context instead of the entire file
- **Context return**: Includes file span metadata for verification

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\workspace\\sample-app\\config\\app.yaml",
            "start_line": 1,
            "end_line": 12,
            "lines_total": 12,
            "new_context": [
                "1: debug: true",
                "2: host: api.example.com",
                "...",
                "11: retries: 3",
                "12: timeout: 30"
            ],
            "bytes_written": 164
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
            "filepath": "d:\\workspace\\sample-app\\config\\missing.yaml",
            "reason": "File not found"
        }
    ]
}
```

### Examples

**Example 1: Replace a configuration file**

```python
edit_file_replace_content(ops=[
    {"path": "config/app.yaml", "content": "debug: true\nhost: api.example.com\n"}
])
```

**Example 2: Batch replace generated files**

```python
edit_file_replace_content(ops=[
    {"path": "docs/example-a.md", "content": "# Example A\n"},
    {"path": "docs/example-b.md", "content": "# Example B\n"}
])
```

**Example 3: Clear a file**

```python
edit_file_replace_content(ops=[
    {"path": "tmp/output.log", "content": ""}
])
```

### Common Gotchas

- **No creation**: The tool fails if the file does not exist. Use `edit_file_create` first.
- **Context capping**: Large files return a shortened preview. Use metadata such as `lines_total` to confirm the replacement span.
- **Atomic rollback**: Original content is restored automatically if any operation in the batch fails.

---

## edit_file_insert_at_boundary

**Purpose**: Insert text at the beginning or end of existing files.

**Function signature:**

```python
def edit_file_insert_at_boundary(position: Literal["bof", "eof"], ops: list[dict]) -> dict
```

### InsertBoundaryOp Model

```python
{
    "path": str,       # File path (workspace-relative or absolute)
    "content": str     # Content to insert
}
```

### Behavior

- **All files must exist**: Fails if any target file does not exist
- **Two insertion modes**:
  - `bof`: Insert at the beginning of the file
  - `eof`: Insert at the end of the file
- **Line-oriented insertion**: Content is inserted as new line(s)
- **Atomic batching**: Multiple inserts succeed or fail together
- **Context return**: Returns the changed region with nearby context

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\workspace\\sample-app\\services\\example_service.py",
            "start_line": 1,
            "end_line": 2,
            "new_context": [
                "1: from typing import Any",
                "2: ",
                "3: class ExampleService:",
                "4:     pass"
            ],
            "bytes_written": 25
        }
    ],
    "failed_ops": []
}
```

### Examples

**Example 1: Add an import block at the top of a file**

```python
edit_file_insert_at_boundary(
    position="bof",
    ops=[
        {"path": "services/example_service.py", "content": "from typing import Any\n\n"}
    ],
)
```

**Example 2: Append a helper at the end of a file**

```python
edit_file_insert_at_boundary(
    position="eof",
    ops=[
        {"path": "helpers/example.py", "content": "\n\ndef cleanup() -> None:\n    pass\n"}
    ],
)
```

**Example 3: Add the same footer to multiple docs**

```python
edit_file_insert_at_boundary(
    position="eof",
    ops=[
        {"path": "docs/example-a.md", "content": "\n_Updated by Acme Corp._\n"},
        {"path": "docs/example-b.md", "content": "\n_Updated by Acme Corp._\n"}
    ],
)
```

### Common Gotchas

- **No file creation**: The file must already exist. Use `edit_file_create` first if needed.
- **Boundary only**: This tool only supports `bof` and `eof`. Use `edit_file_insert_at_line` when you need to insert near existing content.
- **Batch semantics**: All inserts in the call are applied atomically.

---

## edit_file_insert_at_line

**Purpose**: Insert text before or after a uniquely matching content anchor.

**Function signature:**

```python
def edit_file_insert_at_line(ops: list[dict]) -> dict
```

### InsertLineOp Model

```python
{
    "path": str,                    # File path (workspace-relative or absolute)
    "content": str,                 # Content to insert
    "anchor": str,                  # Content substring that must match exactly one line
    "position": "before|after"    # Insert before or after the anchor line
}
```

### Behavior

- **All files must exist**: Fails if any target file does not exist
- **Anchor-based targeting**: Each `anchor` must match exactly one line in the target file
- **Two insertion modes**:
  - `before`: Insert before the anchor line
  - `after`: Insert after the anchor line
- **Line-oriented insertion**: Content is inserted as new line(s)
- **Atomic batching**: Multiple inserts succeed or fail together
- **Context return**: Returns the changed region with nearby context

### Response (success)

```python
{
    "status": "applied",
    "applied_ops": [
        {
            "index": 0,
            "filepath": "d:\\workspace\\sample-app\\services\\example_service.py",
            "start_line": 8,
            "end_line": 8,
            "new_context": [
                "6: def run_example() -> None:",
                "7:     \"\"\"Run the example workflow.\"\"\"",
                "8:     logger.info(\"Starting run\")",
                "9:     result = build_payload()",
                "10:     return None"
            ],
            "bytes_written": 34
        }
    ],
    "failed_ops": []
}
```

### Examples

**Example 1: Insert a log line after a docstring**

```python
edit_file_insert_at_line(ops=[
    {
        "path": "services/example_service.py",
        "content": "    logger.info(\"Starting example run\")\n",
        "anchor": '    """Run the example workflow."""',
        "position": "after",
    }
])
```

**Example 2: Insert a comment before a specific statement**

```python
edit_file_insert_at_line(ops=[
    {
        "path": "services/example_service.py",
        "content": "    # Validate input before building the payload\n",
        "anchor": "    payload = build_payload()",
        "position": "before",
    }
])
```

**Example 3: Batch anchor-based inserts**

```python
edit_file_insert_at_line(ops=[
    {
        "path": "services/example_service.py",
        "content": "from typing import Any\n",
        "anchor": "import logging",
        "position": "after",
    },
    {
        "path": "services/example_service.py",
        "content": "    logger.debug(\"Finished example run\")\n",
        "anchor": "    return None",
        "position": "before",
    }
])
```

### Common Gotchas

- **Unique anchor required**: The anchor must match exactly one line. Ambiguous or missing anchors fail the batch.
- **No column addressing**: Column-based insertion was removed. Use a more specific anchor or a different editing tool.
- **Anchor matching is content-based**: Pick stable, distinctive anchor text to avoid accidental breakage.

---

## Atomicity Guarantees

All editing tools enforce atomic transactions:

1. **Pre-flight validation**: All paths are resolved and validated before any file modifications begin
2. **Staging**: Changes are prepared in memory or temporary files first
3. **Atomic commit**: Writes are committed together
4. **Complete rollback**: Any failure restores the original state
5. **No partial success**: A failed call returns `status: "failed"` with no applied mutations

**Example rollback scenario:**

```python
edit_file_replace_content(ops=[
    {"path": "config/app.yaml", "content": "debug: true\n"},
    {"path": "config/worker.yaml", "content": "debug: false\n"},
    {"path": "config/missing.yaml", "content": "debug: false\n"}
])
# Result: every file keeps its original contents
# Response: status="failed", applied_ops=[], failed_ops=[{index: 2, reason: "File not found"}]
```

---

## Coordinate Space Rule

**Critical**: Current editing tools avoid most numeric coordinate drift by using file boundaries, full-file replacement, or content anchors.

**Why?** Content-aware targeting is more stable than hand-managed line and column math, especially in batch operations.

**Implementation:**

- `edit_file_insert_at_boundary` has no line or column coordinates to maintain.
- `edit_file_insert_at_line` resolves insert locations by unique anchor text.
- Boundary-based tools such as `edit_file_replace_by_content` and `edit_file_move_by_content` validate the source range against the original file contents before committing changes.

**Example:**

```python
edit_file_insert_at_line(ops=[
    {
        "path": "services/example_service.py",
        "content": "from typing import Any\n",
        "anchor": "import logging",
        "position": "after",
    },
    {
        "path": "services/example_service.py",
        "content": "    logger.debug(\"Finished example run\")\n",
        "anchor": "    return None",
        "position": "before",
    }
])
# Each insert location is resolved by anchor text instead of manually adjusted line numbers
```

---

## Usage Patterns

### Pattern 1: Scaffold New Files

```python
edit_file_create(files=[
    {"path": "services/example/session_service.py", "content": "# Session service\n"},
    {"path": "services/example/token_service.py", "content": "# Token service\n"}
])
```

### Pattern 2: Batch Configuration Updates

```python
edit_file_replace_content(ops=[
    {"path": "config/dev.yaml", "content": "debug: true\nport: 8000\n"},
    {"path": "config/staging.yaml", "content": "debug: false\nport: 8001\n"},
    {"path": "config/prod.yaml", "content": "debug: false\nport: 443\n"}
])
```

### Pattern 3: Add Headers or Footers

```python
edit_file_insert_at_boundary(
    position="bof",
    ops=[
        {"path": "services/example_service.py", "content": "from __future__ import annotations\n\n"}
    ],
)

edit_file_insert_at_boundary(
    position="eof",
    ops=[
        {"path": "docs/example-a.md", "content": "\n_Last reviewed by Jane Doe._\n"}
    ],
)
```

### Pattern 4: Insert Near Stable Anchors

```python
edit_file_insert_at_line(ops=[
    {
        "path": "services/example_service.py",
        "content": "    logger.info(\"Starting example run\")\n",
        "anchor": '    """Run the example workflow."""',
        "position": "after",
    },
    {
        "path": "services/example_service.py",
        "content": "    logger.debug(\"Finished example run\")\n",
        "anchor": "    return None",
        "position": "before",
    }
])
```

---

## Error Handling

All tools return structured error responses:

```python
{
    "status": "failed",
    "applied_ops": [],
    "failed_ops": [
        {
            "index": 2,
            "filepath": "d:\\workspace\\sample-app\\config\\missing.yaml",
            "reason": "File not found"
        }
    ]
}
```

**Common error reasons:**

- `"File already exists"` (`edit_file_create`)
- `"File not found"` (`edit_file_replace_content`, insert tools, move tools)
- `"Duplicate path in batch"` (batch editing tools)
- `"Anchor matched zero or multiple lines"` (`edit_file_insert_at_line`)
- `"Boundary matched zero or multiple ranges"` (`edit_file_replace_by_content`, `edit_file_move_by_content`)
- `"Permission denied"` (all editing tools)
- `"Disk full"` (all editing tools)

**Error recovery:**

1. All operations are rolled back automatically
2. No manual cleanup is required
3. Check `failed_ops` for the specific error details
4. Fix the issue and retry the full batch

---

## Performance Considerations

### Batch Operations

Prefer a single batch call over multiple sequential calls when possible:

- **Better atomicity**: One failure rolls back the whole planned change
- **Better performance**: Validation and write phases happen once per batch
- **Cleaner call graph**: Fewer tool invocations means less orchestration overhead

### Stable Anchors and Boundaries

- Pick distinctive anchor text for `edit_file_insert_at_line`
- Pick stable start and end markers for `edit_file_replace_by_content` and `edit_file_move_by_content`
- Prefer boundary- or anchor-based edits over fragile manual coordinate bookkeeping

### Context Return Size

Tools limit returned context to keep responses compact:

- `edit_file_create`: Opening lines of each created file
- `edit_file_replace_content`: Summarized replacement context
- `edit_file_insert_at_boundary`: Changed region with nearby context
- `edit_file_insert_at_line`: Changed region with nearby context

If you need the full file contents, read the file separately after the mutation succeeds.

---

## Choosing the Right Tool

 | Scenario | Tool | Why |
 | ---------- | ------ | ----- |
 | Create new files | `edit_file_create` | Auto-creates parent directories and fails on existing files |
 | Replace an entire file | `edit_file_replace_content` | Best fit for whole-file rewrites |
 | Make targeted string edits | `edit_file_replace_string` | Exact-match replacement with expected-count safety |
 | Replace a bounded block | `edit_file_replace_by_content` | Uses content boundaries instead of line numbers |
 | Insert at top or bottom | `edit_file_insert_at_boundary` | Direct boundary insertion with no anchor selection |
 | Insert near existing content | `edit_file_insert_at_line` | Uses a unique content anchor instead of line numbers |
 | Move or rename a file | `edit_file_move` | Single-call file move within the workspace |
 | Move a bounded block | `edit_file_move_by_content` | Extracts or relocates content using boundaries |

---

## Related Tools

- **`edit_file_move_by_content`**: Move or extract text between locations using content boundaries
- **`edit_file_replace_string`**: Apply exact string replacements atomically within one file
- **`read_module_source`**: Read function or class source before editing
- **`lint_project_backend`**: Validate Python changes after file mutations
