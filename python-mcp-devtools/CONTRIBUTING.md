# Contributing to python-mcp-devtools

We welcome contributions! This guide explains how to add new tools to the package.

## Architecture Overview

The package is organized into:

```
Tools (MCP functions)
├── project_list_routes      # Discover API routes
├── trace_calls              # Trace call chains
├── project_check_api_coverage  # Backend-frontend integration
└── trace_endpoint           # FastAPI DI resolution
    ↓
Helpers (Shared utilities)
├── config_loader            # Load and validate config
└── route_parser             # Parse routes via AST
```

**Design Principles:**
- **Zero-config defaults**: Tools work immediately without configuration
- **Config-driven**: All project-specific patterns in JSON, not code
- **No framework-specific imports**: Tools are generic across Python projects
- **Fully typed**: All functions and parameters have type annotations
- **Dependency injection**: Configuration passed as parameters, not global state

## Adding a New Tool

### Step 1: Create the Tool Module

Create `src/mcp_devtools/my_new_tool.py`:

```python
"""Brief description of what the tool does.

Example usage:
    from mcp_devtools.my_new_tool import my_new_tool
    result = my_new_tool("project_root", config=None)
"""

from __future__ import annotations

__all__ = ["my_new_tool"]

from pathlib import Path
from typing import Any

from .helpers.config_loader import load_config, get_backend_config


def my_new_tool(
    project_root: Path | str | None = None,
    config: dict | None = None
) -> dict[str, Any]:
    """Do something useful with the codebase.
    
    Configuration used:
        my_tool.some_setting: Description of what it does
            Default: default_value
    
    Args:
        project_root: Root directory of project (str or Path)
        config: Optional config dict. If not provided, loads from project_root.
        
    Returns:
        Dict with results and optional error field
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent.parent
    else:
        project_root = Path(project_root)
    
    # Load config if not provided (dependency injection)
    if config is None:
        config = load_config(project_root)
    
    backend_config = get_backend_config(config)
    
    # Your implementation here
    results = []
    
    return {
        "results": results,
        "count": len(results),
    }
```

### Step 2: Add Config Schema Entry

Update `config_schema.json` to document your tool's configuration:

```json
{
  "my_tool": {
    "description": "Configuration for my_new_tool",
    "type": "object",
    "properties": {
      "some_setting": {
        "description": "What this setting does",
        "type": "string",
        "default": "default_value"
      }
    }
  }
}
```

### Step 3: Export the Tool

Update `src/mcp_devtools/__init__.py`:

```python
__all__ = [
    "project_list_routes",
    "trace_calls",
    "project_check_api_coverage",
    "trace_endpoint",
    "my_new_tool",  # Add here
]
```

### Step 4: Create Tests

Create `tests/test_my_new_tool.py`:

```python
"""Tests for my_new_tool."""

import pytest
from mcp_devtools.my_new_tool import my_new_tool


def test_my_new_tool_works_without_config():
    """Tool should work with default configuration."""
    result = my_new_tool(".")
    assert isinstance(result, dict)
    assert "count" in result or "error" in result


def test_my_new_tool_with_config():
    """Tool should work with custom configuration."""
    config = {
        "my_tool": {
            "some_setting": "custom_value"
        }
    }
    result = my_new_tool(".", config=config)
    assert isinstance(result, dict)
```

### Step 5: Write Documentation

Create `docs/MY_NEW_TOOL.md`:

```markdown
# my_new_tool

Brief description of what the tool does and why it's useful.

## Usage

### Basic

```python
from mcp_devtools.my_new_tool import my_new_tool
result = my_new_tool("path/to/project")
```

### With Configuration

```python
from mcp_devtools.helpers.config_loader import load_config
from mcp_devtools.my_new_tool import my_new_tool

config = load_config("path/to/project")
result = my_new_tool("path/to/project", config=config)
```

## Configuration

```json
{
  "my_tool": {
    "some_setting": "value"
  }
}
```

## Output

The tool returns a dictionary with:
- `results`: Main output
- `count`: Number of results
- `error`: Optional error message
```

## Design Guidelines

### Do's

- ✅ Accept `project_root` as `Path | str | None`
- ✅ Accept optional `config` parameter for dependency injection
- ✅ Use fully qualified type hints
- ✅ Provide default behavior without config
- ✅ Handle missing files/directories gracefully
- ✅ Return errors in the result dict, don't raise exceptions
- ✅ Use AST parsing for static analysis (no code execution)
- ✅ Document configuration in docstring
- ✅ Test with and without config

### Don'ts

- ❌ Import nomarr or project-specific modules
- ❌ Read config/env vars at module import time
- ❌ Create global state or mutable defaults
- ❌ Execute code from the analyzed project
- ❌ Make assumptions about directory structure without config
- ❌ Require external programs (git, node, etc)
- ❌ Modify the codebase being analyzed
- ❌ Use print() for output (return dict instead)

## Making Your Tool Generic

### Pattern: File Path Globs

Instead of hardcoding file paths:

```python
# ❌ Bad - nomarr-specific
interface_files = project_root.glob("nomarr/interfaces/api/**/*.py")

# ✅ Good - configurable
interface_globs = config.get("backend", {}).get("interface_globs", [])
interface_files = []
for glob_pattern in interface_globs:
    interface_files.extend(project_root.glob(glob_pattern))
```

### Pattern: Code Patterns/Decorators

Instead of hardcoding regex patterns:

```python
# ❌ Bad - only FastAPI
decorators = ["@router.get", "@router.post"]

# ✅ Good - configurable
decorators = config.get("backend", {}).get("routes", {}).get("decorators", [])
```

### Pattern: Module Filtering

Instead of hardcoding module names:

```python
# ❌ Bad - nomarr-specific
if qualified_name.startswith("nomarr."):
    include_in_trace = True

# ✅ Good - configurable
include_patterns = config.get("tracing", {}).get("include_patterns", ["app.*"])
exclude_modules = config.get("tracing", {}).get("exclude_modules", [])

def should_include(name):
    for exclude in exclude_modules:
        if name.startswith(exclude):
            return False
    for pattern in include_patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False
```

## Extending Existing Tools

If your contribution fits into an existing tool:

1. Update that tool's configuration section in `config_schema.json`
2. Add logic to the tool module using the new config keys
3. Update tests to cover the new configuration
4. Document the new config in the tool's docstring

## Community Tools

Want to add tools for other languages/frameworks? Consider creating a separate package:

- `python-mcp-devtools-java` for Java projects
- `python-mcp-devtools-typescript` for TypeScript tools
- `python-mcp-devtools-rust` for Rust analysis

Use the same config-driven architecture for consistency.

## Testing Your Tool

Run tests before submitting:

```bash
pytest tests/test_my_new_tool.py -v
ruff check src/mcp_devtools/my_new_tool.py
mypy src/mcp_devtools/my_new_tool.py
```

## Submitting a Contribution

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-tool`
3. Implement the tool following the guidelines above
4. Write tests and documentation
5. Run linting and tests
6. Submit a pull request with a clear description

We review contributions within 1-2 weeks.

---

## Questions?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for more details or open an issue on GitHub.
