---
name: MCP Tools
description: Guidelines for implementing MCP tool functions
applyTo: scripts/mcp/tools/**
---

# MCP Tools Implementation

**Purpose:** Expose Nomarr's code analysis capabilities as callable functions for AI agents.

Tools are **functions** that AI can invoke with arguments to perform actions or retrieve information.

---

## Tool Definition Pattern

### Basic Structure

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nomarr")

@mcp.tool()
def tool_name(
    required_param: str,
    optional_param: int = 10
) -> dict[str, Any]:
    """Clear description of what this tool does.
    
    Args:
        required_param: What this parameter represents
        optional_param: Optional parameter with default
    
    Returns:
        Structured data about the result
    """
    # Implementation
    return {"result": value}
```

### Key Requirements

1. **Decorator:** Always use `@mcp.tool()`
2. **Type Hints:** Full type annotations on all parameters and return
3. **Docstring:** Clear description of purpose, params, returns
4. **Structure:** Return dict/Pydantic model, not plain strings
5. **Errors:** Raise exceptions with helpful messages

---

## Nomarr Tool Categories

### Python Code Navigation

**Purpose:** Help AI understand Nomarr's Python codebase structure.

```python
@mcp.tool()
def discover_api(module_name: str) -> dict:
    """Show public API of any Python module.
    
    Returns signatures, methods, classes, constants without
    loading the full source code. Fast overview.
    """
    # Parse AST, extract public symbols
    return {
        "Function": ["func1", "func2"],
        "Class": ["ClassA", "ClassB"],
        "Constant": ["CONFIG", "VERSION"]
    }

@mcp.tool()
def get_source(qualified_name: str, context_lines: int = 0) -> dict:
    """Get source code of specific function/method/class.
    
    Args:
        qualified_name: Like 'module.Class.method'
        context_lines: Lines before/after for context
    """
    return {
        "name": qualified_name,
        "type": "function",
        "file": str(file_path),
        "source": source_code,
        "line": start_line,
        "line_count": num_lines
    }
```

### Call Tracing

**Purpose:** Understand how code flows through layers.

```python
@mcp.tool()
def trace_endpoint(endpoint: str) -> dict:
    """Trace FastAPI endpoint through DI to service methods.
    
    Higher-level tool that:
    1. Finds endpoint function
    2. Extracts Depends() injections
    3. Finds service method calls
    4. Traces full call chain
    """
    return {
        "endpoint": endpoint,
        "handler": "function_name",
        "dependencies": [...],
        "call_chain": [...]
    }
```

### Quality Checks

**Purpose:** Run linters and type checkers.

```python
@mcp.tool()
def lint_backend(path: str | None = None) -> dict:
    """Run ruff, mypy, and import-linter.
    
    Args:
        path: Specific file/dir, or None for all
    """
    return {
        "ruff": {"passed": True, "errors": []},
        "mypy": {"passed": False, "errors": [...]},
        "import_linter": {"passed": True}
    }
```

---

## Input Validation

Validate early, fail fast with clear messages:

```python
@mcp.tool()
def read_file(
    file_path: str,
    start_line: int,
    end_line: int
) -> dict[str, Any]:
    """Read line range from file."""
    
    # Validate parameters
    if not file_path:
        raise ValueError("file_path cannot be empty")
    
    if start_line < 1:
        raise ValueError(f"start_line must be >= 1, got {start_line}")
    
    if end_line < start_line:
        raise ValueError(
            f"end_line ({end_line}) must be >= start_line ({start_line})"
        )
    
    # Check file exists
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    # Perform operation
    ...
```

---

## Return Value Structure

### Use Consistent Schemas

**Good:**
```python
from pydantic import BaseModel, Field

class SymbolInfo(BaseModel):
    """Information about a code symbol."""
    name: str = Field(description="Symbol name")
    type: str = Field(description="Symbol type (function, class, etc)")
    file: str = Field(description="File path")
    line: int = Field(description="Starting line")
    source: str | None = Field(default=None, description="Source code")

@mcp.tool()
def locate_symbol(symbol_name: str) -> list[SymbolInfo]:
    """Find all definitions of a symbol."""
    return [SymbolInfo(...) for match in matches]
```

**Bad:**
```python
@mcp.tool()
def locate_symbol(symbol_name: str) -> str:
    """Returns unstructured text - hard to parse."""
    return f"Found {name} at {file}:{line}"
```

### Include Metadata

```python
@mcp.tool()
def search_text(file_path: str, search_string: str) -> dict:
    """Search for text in file."""
    matches = perform_search(file_path, search_string)
    
    return {
        "file_path": file_path,
        "search_string": search_string,
        "match_count": len(matches),
        "matches": matches,
        "searched_at": datetime.now().isoformat()
    }
```

---

## Error Handling

### Error Categories

```python
@mcp.tool()
def get_source(qualified_name: str) -> dict:
    """Get source with clear error messages."""
    
    # User input errors
    if not qualified_name:
        raise ValueError("qualified_name cannot be empty")
    
    # Symbol not found
    try:
        symbol = locate_symbol_in_ast(qualified_name)
    except SymbolNotFoundError:
        raise ValueError(
            f"Symbol not found: {qualified_name}. "
            "Use locate_symbol() to find available symbols."
        )
    
    # File system errors
    try:
        source = Path(symbol.file).read_text()
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Source file not found: {symbol.file}. "
            "File may have been moved or deleted."
        )
    
    return {"source": source, ...}
```

### Helpful Error Messages

Include:
- What went wrong
- What was expected
- How to fix it
- Related tools that might help

```python
raise ValueError(
    f"Module '{module_name}' not found in nomarr package. "
    f"Available top-level modules: {', '.join(available_modules)}. "
    "Use discover_api('nomarr') to see all packages."
)
```

---

## Output Size Limits

AI contexts have token limits. Don't return massive outputs:

```python
@mcp.tool()
def list_routes(route_path: str | None = None) -> dict:
    """List API routes with size limits."""
    routes = discover_all_routes()
    
    # Filter if path specified
    if route_path:
        routes = [r for r in routes if route_path in r["path"]]
    
    # Warn if too many results
    if len(routes) > 50:
        return {
            "warning": f"Found {len(routes)} routes, showing first 50",
            "hint": "Use route_path parameter to filter results",
            "routes": routes[:50],
            "total_count": len(routes)
        }
    
    return {"routes": routes, "total_count": len(routes)}
```

### Truncation Strategy

```python
MAX_SOURCE_LINES = 100

@mcp.tool()
def get_source(qualified_name: str) -> dict:
    """Get source with truncation for large symbols."""
    source_lines = extract_source(qualified_name)
    
    if len(source_lines) > MAX_SOURCE_LINES:
        return {
            "name": qualified_name,
            "source": "\n".join(source_lines[:MAX_SOURCE_LINES]),
            "truncated": True,
            "line_count": len(source_lines),
            "hint": "Use context_lines parameter or read_file for full source"
        }
    
    return {
        "name": qualified_name,
        "source": "\n".join(source_lines),
        "truncated": False,
        "line_count": len(source_lines)
    }
```

---

## Performance Optimization

### Cache Expensive Operations

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=256)
def _parse_file_ast(file_path: str, file_hash: str):
    """Cache AST parsing by file content hash."""
    return ast.parse(Path(file_path).read_text())

def get_file_hash(path: Path) -> str:
    """Get hash of file content for cache key."""
    return hashlib.md5(path.read_bytes()).hexdigest()

@mcp.tool()
def discover_api(module_name: str) -> dict:
    """Uses cached AST parsing."""
    file_path = resolve_module_path(module_name)
    file_hash = get_file_hash(Path(file_path))
    
    # Cache hit if file unchanged
    ast_tree = _parse_file_ast(file_path, file_hash)
    return extract_api_from_ast(ast_tree)
```

### Lazy Loading

```python
@mcp.tool()
def trace_calls(function: str) -> dict:
    """Trace call chain with lazy loading."""
    # Don't load all files upfront
    entry_point = locate_function(function)
    
    # Trace on-demand as we walk the call graph
    call_chain = []
    for callee in walk_calls(entry_point):
        # Only parse files as needed
        call_chain.append(analyze_call(callee))
    
    return {"function": function, "calls": call_chain}
```

---

## Tool Composition

Tools should be composable - one tool's output feeds another:

```python
# Step 1: Discover what's available
@mcp.tool()
def discover_api(module_name: str) -> dict:
    """Returns list of symbols."""
    return {"Function": ["func1", "func2"], ...}

# Step 2: Get details about specific symbol
@mcp.tool()
def get_source(qualified_name: str) -> dict:
    """Takes symbol name from discover_api output."""
    return {"source": code, ...}

# Step 3: Understand how it's used
@mcp.tool()
def trace_calls(function: str) -> dict:
    """Takes function name from get_source output."""
    return {"call_chain": [...]}
```

AI agents can chain tools:
1. `module_discover_api("nomarr.services")` → see available services
2. `module_get_source("nomarr.services.ConfigService")` → see implementation
3. `trace_calls("ConfigService.load_config")` → see how it's used

---

## Testing Tools

### Unit Tests

```python
import pytest
from scripts.mcp.tools.discover_api import discover_api

def test_discover_api_success():
    """Test successful module discovery."""
    result = discover_api("nomarr.helpers.exceptions")
    
    assert "Class" in result
    assert "NomarrException" in result["Class"]

def test_discover_api_invalid_module():
    """Test error handling for invalid module."""
    with pytest.raises(ValueError, match="Module .* not found"):
        discover_api("nonexistent.module")
```

### Integration Tests

```python
@pytest.mark.integration
async def test_tool_via_mcp():
    """Test tool through actual MCP server."""
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Call tool via MCP
            result = await session.call_tool(
                "discover_api",
                arguments={"module_name": "nomarr.services"}
            )
            
            # Verify structured output
            assert result.structuredContent is not None
            assert "Function" in result.structuredContent
```

---

## Summary Checklist

Before committing a tool:

- [ ] Uses `@mcp.tool()` decorator
- [ ] Full type hints (params + return)
- [ ] Clear docstring with Args/Returns
- [ ] Returns structured data (dict/Pydantic)
- [ ] Validates inputs early
- [ ] Helpful error messages with context
- [ ] Limits output size for large results
- [ ] Read-only/idempotent operation
- [ ] Unit tests for success and error cases
- [ ] Integration test via MCP client
- [ ] Tool name is descriptive and follows `verb_noun` pattern
