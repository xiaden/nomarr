---
name: MCP Server Basics
description: Core MCP architecture patterns and server setup
applyTo: scripts/mcp/**
---

# MCP Server Development - Core Concepts

**Purpose:** Build Model Context Protocol servers that expose Nomarr's capabilities to AI agents through standardized tools, resources, and prompts.

---

## What is MCP?

Model Context Protocol (MCP) is an **open protocol** that standardizes how AI applications connect to external data sources and tools. Think of it as "USB-C for AI" - a universal interface for context.

### Architecture

```
AI Application (Client) ←→ MCP Server ←→ Your Application (Nomarr)
```

- **Client**: AI agents, IDEs, chat interfaces
- **Server**: Exposes capabilities via MCP protocol
- **Application**: Your actual business logic (Nomarr)

---

## Server Capabilities

MCP servers can expose three types of capabilities:

1. **Tools** - Functions the AI can call (with side effects allowed)
   - Example: `lint_project_backend()`, `trace_project_endpoint()`
   - Use `@mcp.tool()` decorator

2. **Resources** - Data the AI can read (via URIs)
   - Example: `file://documents/{name}`, `config://settings`
   - Use `@mcp.resource()` decorator

3. **Prompts** - Reusable templates for common tasks
   - Example: "Review this code for security issues"
   - Use `@mcp.prompt()` decorator

---

## Core Principles

### Use FastMCP for Simplicity

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("server-name")
```

FastMCP provides decorator-based APIs - much simpler than low-level handlers.

### Keep Tools Focused

**Good:**
```python
@mcp.tool()
def get_source(qualified_name: str) -> dict:
    """Get source code of a specific function/class."""
    # Single, clear purpose
    return {"source": code, "file": path, "line": line_no}
```

**Bad:**
```python
@mcp.tool()
def analyze_code(action: str, target: str, options: dict) -> Any:
    """Do various code analysis tasks."""
    # Too generic, unclear purpose
    if action == "get_source": ...
    elif action == "trace_module_calls": ...
```

### Return Structured Data

Use Pydantic models or TypedDict for clear schemas:

```python
from pydantic import BaseModel, Field

class SourceInfo(BaseModel):
    source: str = Field(description="Source code")
    file: str = Field(description="Absolute file path")
    line: int = Field(description="Starting line number")
    line_count: int = Field(description="Number of lines")

@mcp.tool()
def get_source(qualified_name: str) -> SourceInfo:
    """Returns structured source information."""
    return SourceInfo(...)
```

### Handle Errors Clearly

```python
@mcp.tool()
def read_file(file_path: str, start_line: int, end_line: int) -> dict:
    """Read file with clear error messages."""
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if start_line < 1 or end_line < start_line:
        raise ValueError(f"Invalid line range: {start_line}-{end_line}")
    
    # ... read file
```

Errors are automatically sent to clients as tool failures.

---

## Logging Best Practices

**CRITICAL:** MCP uses stdout for JSON-RPC. **Never** write to stdout!

```python
import logging
import sys

# ALWAYS configure logging to stderr
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s: %(message)s",
    stream=sys.stderr,  # Critical: MCP uses stdout for JSON-RPC
)

# Suppress noisy third-party loggers
for logger_name in ["asyncio", "urllib3", "httpcore"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)
```

**Never:**
- `print()` statements
- `sys.stdout.write()`
- Loggers configured to stdout

---

## File Organization

```
scripts/mcp/
├── __init__.py
├── nomarr_mcp.py          # Main server entry point
├── tools/                 # Tool implementations
│   ├── __init__.py
│   ├── discover_api.py
│   ├── trace_project_endpoint.py
│   └── helpers/           # Shared utilities
├── resources/             # Resource providers (future)
├── prompts/               # Prompt templates (future)
└── context/               # Context managers (future)
```

### Main Server Pattern

```python
#!/usr/bin/env python3
"""MCP Server for Nomarr."""

import logging
import sys
from mcp.server.fastmcp import FastMCP
from scripts.mcp import tools

# Configure logging FIRST
logging.basicConfig(
    level=logging.WARNING,
    stream=sys.stderr,
)

# Create server
mcp = FastMCP("nomarr")

# Register capabilities (tools auto-register via decorators)

if __name__ == "__main__":
    mcp.run()  # Defaults to stdio transport
```

---

## Static Analysis Philosophy

**Nomarr's MCP server provides read-only static analysis tools.**

This means:
- **No code execution** - Parse AST, don't run code
- **No file modifications** - Read-only operations
- **No side effects** - Idempotent queries
- **Fast responses** - Cache where possible

Tools should:
1. Parse source files (AST analysis)
2. Return structured metadata
3. Let AI agents make decisions

**We don't:**
- Execute Python code in tools
- Modify files (that's for other layers)
- Infer runtime behavior (unless explicitly tracing)

---

## Type Hints Are Mandatory

MCP uses type hints to generate JSON schemas:

```python
# Good: Full type hints
@mcp.tool()
def search_text(file_path: str, search_string: str) -> dict[str, list[str]]:
    """Type hints generate proper schema."""
    return {"matches": [...]}

# Bad: Missing types
@mcp.tool()
def search_text(file_path, search_string):  # No schema generated!
    return {"matches": [...]}
```

**Always include:**
- Parameter types
- Return type
- Pydantic models for complex structures

---

## Testing MCP Servers

### Manual Testing

```bash
# Run server
python -m scripts.mcp.nomarr_mcp

# Server will wait for JSON-RPC input on stdin
# Use MCP Inspector or Claude Desktop for interactive testing
```

### Integration with VS Code

Configure in `.vscode/settings.json`:

```json
{
  "mcp.servers": {
    "nomarr": {
      "command": "python",
      "args": ["-m", "scripts.mcp.nomarr_mcp"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

---

## Common Patterns

### Tool with Context

Use `Context` to access session state:

```python
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

mcp = FastMCP("contextual-server")

@mcp.tool()
async def interactive_tool(
    query: str,
    ctx: Context[ServerSession, None]
) -> str:
    """Tool that can interact with client."""
    # Access session info
    # Can use ctx.elicit() for user input
    return f"Processed: {query}"
```

### Async vs Sync

Both work, but prefer async for I/O:

```python
# Sync (fine for fast operations)
@mcp.tool()
def quick_calculation(a: int, b: int) -> int:
    return a + b

# Async (better for I/O)
@mcp.tool()
async def read_large_file(path: str) -> str:
    async with aiofiles.open(path) as f:
        return await f.read()
```

### Error Categories

```python
from pathlib import Path

@mcp.tool()
def read_file(file_path: str) -> str:
    """Categorize errors clearly."""
    path = Path(file_path)
    
    # User error (bad input)
    if not file_path:
        raise ValueError("file_path cannot be empty")
    
    # System error (file system)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Permission error
    if not path.is_file():
        raise ValueError(f"Not a file: {file_path}")
    
    return path.read_text()
```

---

## Performance Considerations

### Limit Output Size

AI contexts have token limits:

```python
@mcp.tool()
def get_large_data(query: str) -> dict:
    """Limit output to avoid token exhaustion."""
    results = perform_query(query)
    
    # Limit to first 100 items
    if len(results) > 100:
        return {
            "results": results[:100],
            "truncated": True,
            "total_count": len(results),
            "hint": "Refine query to see more results"
        }
    
    return {"results": results, "truncated": False}
```

### Cache Static Data

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def parse_module_ast(module_path: str):
    """Cache expensive AST parsing."""
    return ast.parse(Path(module_path).read_text())

@mcp.tool()
def discover_api(module_name: str) -> dict:
    """Uses cached AST parsing."""
    ast_tree = parse_module_ast(resolve_module_path(module_name))
    return extract_api(ast_tree)
```

---

## Summary Checklist

Before committing MCP server code:

- [ ] Uses FastMCP decorator API
- [ ] All logging goes to stderr
- [ ] No print() or stdout writes
- [ ] Full type hints on all tools/resources
- [ ] Clear, focused tool purposes
- [ ] Structured return types (Pydantic/TypedDict)
- [ ] Helpful error messages
- [ ] Output size limited for large results
- [ ] Tools are idempotent and read-only
- [ ] Docstrings describe tool behavior clearly
