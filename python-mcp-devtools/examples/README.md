# Example Configurations for python-mcp-devtools

This directory contains example configuration files for different framework combinations.

## Available Examples

- `fastapi_react.json` - FastAPI backend + React frontend
- `flask_vue.json` - Flask backend + Vue frontend  
- `django_svelte.json` - Django backend + Svelte frontend

## Using Examples

Copy an example configuration to your project root as `mcp_config.json` and customize the patterns for your specific codebase.

```bash
cp examples/fastapi_react.json my_project/mcp_config.json
```

Then edit to match your actual route decorators, API call patterns, and DI patterns.
