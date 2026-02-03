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
| `read_module_api` | Static API discovery using AST (no imports) |
| `read_module_source` | Get source code of functions/classes |
| `locate_module_symbol` | Find symbol definitions across configured paths |
| `trace_module_calls` | Trace function call chains |
| `trace_project_endpoint` | Trace FastAPI endpoints through DI |

### File Reading

| Tool | Description |
|------|-------------|
| `read_file_line` | Quick context around a specific line |
| `read_file_range` | Read a range of lines |
| `search_file_text` | Search for text patterns in files |
| `read_read_file_symbol_at_line` | Get symbol context at a line |

### File Editing

| Tool | Description |
|------|-------------|
| `edit_edit_edit_file_replace_content_content_string` | Multiple string replacements in single write |
| `edit_file_move_text` | Move lines within/between files |
| `edit_file_create` | Create new files atomically (fails if exists) |
| `edit_edit_file_replace_content_content` | Replace entire file contents atomically |
| `edit_edit_file_insert_text` | Insert text at specific positions (bof/eof/before/after line) |
| `edit_edit_file_copy_paste_text` | Copy text from sources to targets (stamp decorator pattern) |

### Project Analysis

| Tool | Description |
|------|-------------|
| `list_project_directory_tree` | Smart directory listing with filtering |
| `project_list_routes` | List API routes by static analysis |
| `analyze_project_api_coverage` | Check frontend usage of backend APIs |

### Linting

| Tool | Description |
|------|-------------|
| `lint_project_backend` | Run ruff, mypy, import-linter |
| `lint_project_frontend` | Run ESLint and TypeScript checks |

### Task Planning

| Tool | Description |
|------|-------------|
| `plan_read` | Parse task plan markdown files |
| `plan_complete_step` | Mark steps complete with annotations |

## File Mutation Capabilities

The server provides 4 atomic file mutation tools designed for bulk editing operations:

- **Batch-first APIs**: All tools accept arrays for atomic multi-file operations
- **Atomic transactions**: All-or-nothing execution with complete rollback on any failure
- **Context as validation**: Returns changed regions with ±2 lines of context to eliminate verification reads
- **Coordinate space rule**: For same-file operations, all coordinates refer to ORIGINAL file state

### Common Use Cases

- **Extract functions to new files**: Create targets → copy code → move/delete originals
- **Stamp decorator across codebase**: Copy same decorator to 50+ methods in one atomic operation
- **Batch configuration updates**: Replace multiple config files atomically
- **Precise insertions**: Add imports, comments, or type hints without string matching

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