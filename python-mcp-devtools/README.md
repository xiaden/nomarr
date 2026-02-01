# python-mcp-devtools

Reusable **config-driven MCP tools** for Python project analysis, code tracing, and API coverage checking. Born from the Nomarr backend and extracted as a standalone package for any Python project.

## Features

- **`project_list_routes`**: Discover and list FastAPI routes via static analysis
- **`trace_calls`**: Trace function/method call chains through Python code
- **`project_check_api_coverage`**: Analyze backend-frontend API endpoint coverage
- **`trace_endpoint`**: Trace FastAPI endpoints through dependency injection layers

All tools are **zero-config by default** with optional JSON configuration for advanced customization.

## Installation

```bash
# From PyPI (when published)
pip install python-mcp-devtools

# From source
pip install -e .

# With dev dependencies
pip install -e ".[dev]"
```

## Quick Start

### Using as MCP Tools

Configure in your MCP client (e.g., Claude IDE):

```json
{
  "tools": [
    {
      "name": "project_list_routes",
      "command": ["python", "-m", "mcp_devtools.project_list_routes"]
    },
    {
      "name": "trace_calls",
      "command": ["python", "-m", "mcp_devtools.trace_calls"]
    },
    {
      "name": "project_check_api_coverage",
      "command": ["python", "-m", "mcp_devtools.project_check_api_coverage"]
    },
    {
      "name": "trace_endpoint",
      "command": ["python", "-m", "mcp_devtools.trace_endpoint"]
    }
  ]
}
```

### Using as Python Library

```python
from mcp_devtools.project_list_routes import project_list_routes
from mcp_devtools.trace_calls import trace_calls

# Without config (uses defaults)
routes = project_list_routes("/path/to/project")
calls = trace_calls("mymodule.MyClass.method", "/path/to/project")

# With config
from mcp_devtools.helpers.config_loader import load_config

config = load_config("/path/to/project")
routes = project_list_routes("/path/to/project", config=config)
```

## Configuration

Create `mcp_config.json` in your project root to customize tool behavior:

```json
{
  "backend": {
    "interface_globs": ["src/interfaces/**/*.py"],
    "service_globs": ["src/services/**/*.py"],
    "component_globs": ["src/components/**/*.py"],
    "workflow_globs": ["src/workflows/**/*.py"],
    "exclude_patterns": ["**/__pycache__", "**/*.pyc", "**/test_*"]
  },
  "frontend": {
    "api_call_patterns": [
      "await fetch\\(['\"](/[^'\"]+)"
    ],
    "source_roots": ["src/", "lib/"]
  },
  "tracing": {
    "max_depth": 10,
    "exclude_modules": ["logging", "sys", "os"],
    "follow_imports": true,
    "show_external": false
  }
}
```

### Configuration Schema

**Backend patterns:**
- `interface_globs`: Paths to interface/entry-point files
- `service_globs`: Paths to service layer implementation
- `component_globs`: Paths to component/domain logic
- `workflow_globs`: Paths to workflow orchestration

**Frontend patterns:**
- `api_call_patterns`: Regex patterns to match API calls (e.g., `fetch()`, `axios.get()`)
- `source_roots`: Root directories to scan for frontend code

**Tracing behavior:**
- `max_depth`: Maximum call chain depth to trace
- `exclude_modules`: Don't trace into these modules (stdlib, third-party)
- `follow_imports`: Whether to follow import chains
- `show_external`: Include calls to external packages

## Tool Reference

### `project_list_routes(project_root, config=None)`

Lists all routes in FastAPI application.

**Parameters:**
- `project_root` (str): Root directory of project
- `config` (dict, optional): Configuration dictionary (loads from `mcp_config.json` if not provided)

**Output:**
```json
[
  {
    "method": "GET",
    "path": "/api/users/{id}",
    "function": "get_user",
    "file": "src/interfaces/api/users.py",
    "line": 42
  }
]
```

### `trace_calls(qualified_name, project_root, config=None)`

Traces all functions/methods called by a given function.

**Parameters:**
- `qualified_name` (str): Fully qualified name (e.g., `mymodule.MyClass.method`)
- `project_root` (str): Root directory of project
- `config` (dict, optional): Configuration dictionary

**Output:**
```json
{
  "function": "mymodule.MyClass.method",
  "calls": [
    {
      "name": "helper_func",
      "qualified": "mymodule.helpers.helper_func",
      "file": "src/helpers.py",
      "line": 15
    }
  ],
  "depth": 2
}
```

### `project_check_api_coverage(filter_mode="used", route_path=None, config=None)`

Analyzes backend-frontend API coverage.

**Parameters:**
- `filter_mode` (str): `"used"`, `"unused"`, or `None` (all endpoints)
- `route_path` (str, optional): Filter to specific route path
- `config` (dict, optional): Configuration dictionary

**Output:**
```json
{
  "backend_endpoints": 25,
  "used_by_frontend": 23,
  "unused": [
    {
      "method": "DELETE",
      "path": "/api/admin/purge",
      "file": "src/interfaces/api/admin.py"
    }
  ],
  "coverage_percent": 92.0
}
```

### `trace_endpoint(qualified_name, project_root, config=None)`

Traces FastAPI endpoint through dependency injection layers.

**Parameters:**
- `qualified_name` (str): Endpoint function name
- `project_root` (str): Root directory of project
- `config` (dict, optional): Configuration dictionary

**Output:**
```json
{
  "endpoint": "get_user",
  "path": "/api/users/{id}",
  "dependencies": [
    {
      "name": "db_session",
      "type": "Session",
      "resolved_from": "src/services/db_service.py:get_session"
    }
  ],
  "call_chain": [
    "get_user (endpoint)",
    "UserService.find (injected dependency)",
    "db.query (component)"
  ]
}
```

## Development

### Running Tests

```bash
pytest
pytest -v --cov=mcp_devtools
```

### Linting & Type Checking

```bash
ruff check .
mypy src/
black --check src/
```

### Building Distribution

```bash
python -m build
```

## Architecture

Tools are organized into layers:

```
Tools (exported MCP functions)
├── project_list_routes
├── trace_calls
├── project_check_api_coverage
└── trace_endpoint
    ↓
Helpers (shared utilities)
├── config_loader (load, validate, and merge configs)
└── route_parser (parse FastAPI routes via AST)
```

**Design principles:**
- **Zero-config defaults**: Tools work immediately without configuration
- **Config-driven**: JSON configuration enables advanced customization
- **No project-specific imports**: Tools are generic and reusable
- **Fully typed**: All functions and parameters are type-annotated
- **Backward compatible**: Tools work with or without config parameter (dependency injection)

## Dependency Direction

Tools depend on helpers but never on project-specific code:

```
[Tools] → [Helpers] → [External Libraries]
```

Never:
- Import `nomarr.*` modules
- Load config or env vars at module import time
- Use global state or mutable defaults

## License

MIT

## Contributing

Extract from the [Nomarr backend](https://github.com/nomarr-dev) and genericized for standalone use. Issues and PRs welcome.

---

For detailed API reference and advanced usage, see [docs/TOOLS.md](docs/TOOLS.md).
