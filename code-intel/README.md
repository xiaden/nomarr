# Code Intel MCP Server

A Model Context Protocol (MCP) server providing semantic code navigation and analysis tools for Python codebases.

## Status: Embedded in Nomarr Monorepo

This MCP server currently lives inside the [Nomarr](https://github.com/yourusername/nomarr) monorepo but is **architecturally independent** and designed to work with any Python codebase.

**Future plan:** Split into its own repository (`code-intel` or `mcp-code-intel`) with independent versioning.

## Why It Exists

Built for navigating clean architecture Python projects without reading entire files. Understands FastAPI dependency injection and layer boundaries. Originally created for the Nomarr project but applicable to any Python codebase with similar patterns.

[Chat Logs showing VSCode Usage](docs/chatlogs.md)

## Installation

```bash
cd code-intel
pip install -e .
```

## Configuration

Copy `mcp_config.example.json` to `mcp_config.json` at workspace root and customize:

```json
{
  "backend": {
    "modules": {
      "search_paths": ["nomarr", "code-intel/src/mcp_code_intel"]
    }
  }
}
```

See [config_schema.json](config_schema.json) for full configuration options.

## Tools

### Code Navigation

| Tool | Description |
|------|-------------|
| `list_project_directory_tree` | List directory contents with smart filtering |
| `read_module_api` | Discover the entire API of any Python module |
| `read_module_source` | Get source code of a function/method/class by import path |
| `read_file_symbol_at_line` | Get full function/class containing a line |
| `locate_module_symbol` | Find all definitions of a symbol across the codebase |
| `trace_module_calls` | Trace function call chains |
| `trace_project_endpoint` | Trace FastAPI endpoints through DI |

### Artifact / ADR Tools

| Tool | Description |
|------|-------------|
| `adr_suggest` | Write staging draft to artifacts/decisions/drafts/ for review |
| `adr_commit` | Write an approved ADR to disk in artifacts/decisions/ |
| `adr_read` | Read and parse an existing Architecture Decision Record |
| `adr_search` | Search ADRs by tag, status, and/or text query |

### Design Doc Tools

| Tool | Description |
|------|-------------|
| `dd_create` | Create a new Design Document markdown file |
| `dd_read` | Read and parse an existing Design Document |
| `dd_archive` | Archive a design document from pending to completed |

### Agent Log Tools

| Tool | Description |
|------|-------------|
| `log_write` | Append an entry to an agent's log file |
| `log_read` | Read an agent's log entries with optional filters |

### File Reading

| Tool | Description |
|------|-------------|
| `read_file_line` | Quick error context (target line + 2 lines around) |
| `read_file_line_range` | Read a range of lines from any file (max 100 lines) |
| `search_file_text` | Find exact text in files with 2-line context |


### File Editing

| Tool | Description |
|------|-------------|
| `edit_file_create` | Create new files atomically (batch, fails if exists) |
| `edit_file_replace_content` | Replace entire file contents atomically (batch) |
| `edit_file_replace_string` | Apply multiple string replacements atomically (single write) |
| `edit_file_replace_by_content` | Replace a line range identified by content boundaries |
| `edit_file_insert_at_boundary` | Insert text at bof or eof of file(s) |
| `edit_file_insert_at_line` | Insert text before or after a content anchor in file(s) |
| `edit_file_move` | Move/rename a file within the workspace |
| `edit_file_move_by_content` | Move text between locations using content boundaries |

### Linting

| Tool | Description |
|------|-------------|
| `lint_project_backend` | Run ruff, mypy, import-linter (optionally pytest) |
| `lint_project_frontend` | Run ESLint, TypeScript checks, and Vitest |

### Task Planning

| Tool | Description |
|------|-------------|
| `plan_read` | Read a task plan as structured JSON |
| `plan_complete_step` | Mark steps complete with annotations |
| `plan_archive` | Archive a completed task plan from pending to completed |

### Python Introspection

| Tool | Description |
|------|-------------|
| `py_introspect` | Run whitelist-only Python introspection checks in isolated subprocess |

## File Mutation Capabilities

The server provides 8 file editing tools designed for atomic, bulk-safe editing operations:

- `edit_file_create`
- `edit_file_replace_content`
- `edit_file_replace_string`
- `edit_file_replace_by_content`
- `edit_file_insert_at_boundary`
- `edit_file_insert_at_line`
- `edit_file_move`
- `edit_file_move_by_content`

All of them are designed around the same operational principles:

- **Batch-first APIs**: Create, replace, and insert tools accept arrays for atomic multi-file operations
- **Atomic transactions**: All-or-nothing execution with complete rollback on any failure
- **Context as validation**: Mutation responses include changed regions with nearby context so callers can validate without extra reads
- **Content-aware targeting**: Boundary- and anchor-based tools avoid brittle line-number editing where possible

### Common Use Cases

- **Scaffold new files**: Create multiple files and directories in one atomic operation
- **Batch configuration updates**: Replace multiple config files atomically
- **Targeted structural edits**: Replace or move bounded content without relying on fragile line numbers
- **Precise insertions**: Add imports, comments, or helper blocks at file boundaries or near content anchors

See [MCP Tools Reference](docs/mcp-tools-reference.md) for complete API documentation, examples, and usage patterns.

## Running the Server

```bash
# Via Python module
python -m mcp_code_intel

# Or directly
mcp-code-intel
```

## Documentation

- [MCP Tools Reference](docs/mcp-tools-reference.md) - Detailed API documentation
- [Task Plans](instructions/task-plans.md) - Task plan markdown syntax