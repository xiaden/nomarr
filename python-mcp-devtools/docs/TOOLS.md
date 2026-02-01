# MCP DevTools Documentation

## What is python-mcp-devtools?

`python-mcp-devtools` is a standalone package of Model Context Protocol (MCP) tools for static code analysis and navigation of Python projects with frontend components.

## Core Tools

### project_list_routes

Discover all API routes in your backend via static analysis.

**Configuration:**
```json
{
  "backend": {
    "routes": {
      "decorators": ["@router.get", "@router.post", "@app.get", "@app.post"]
    }
  }
}
```

### trace_calls

Trace function call chains through your codebase.

**Configuration:**
```json
{
  "tracing": {
    "include_patterns": ["myapp.*"],
    "max_depth": 10,
    "filter_external": true
  }
}
```

### project_check_api_coverage

Analyze which backend endpoints are actually used by frontend code.

**Configuration:**
```json
{
  "frontend": {
    "api_calls": {
      "patterns": ["api.get", "fetch(", "axios.get"],
      "search_paths": ["src", "components"]
    }
  }
}
```

### trace_endpoint

Trace an API endpoint through dependency injection to service methods.

**Configuration:**
```json
{
  "backend": {
    "dependency_injection": {
      "patterns": ["Depends(", "Inject("]
    }
  }
}
```

## Configuration

All tools use configuration to adapt to your project's patterns. Configuration is loaded from:
1. `mcp_config.json` in project root (highest priority)
2. `.mcp/config.json` in project root
3. Built-in defaults (lowest priority)

See `../../scripts/mcp/config_schema.json` for the complete configuration schema.

## Framework Examples

See `examples/` directory for configuration examples for:
- FastAPI + React
- Flask + Vue
- Django + Svelte
