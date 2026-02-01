# Example Configurations for python-mcp-devtools

This directory contains pre-configured `mcp_config.json` files for common framework combinations.

## Available Examples

- `fastapi_react.json` - FastAPI backend + React frontend (main example, fully documented)
- `flask_vue.json` - Flask backend + Vue.js frontend
- `django_svelte.json` - Django backend + Svelte frontend

## How to Use

1. Copy the example config matching your framework combination to your project root
2. Rename it to `mcp_config.json`
3. Adjust paths to match your project structure
4. Tools will automatically load the config

Example:
```bash
cp fastapi_react.json ../my-project/mcp_config.json
```

Then in your code:
```python
from mcp_devtools.helpers.config_loader import load_config
from mcp_devtools.project_list_routes import project_list_routes

config = load_config(".")  # Automatically loads mcp_config.json
routes = project_list_routes(".", config=config)
```

## Configuration Schema

All config files follow the schema defined in `../config_schema.json`. Each example includes comments explaining:
- Backend patterns (route decorators, directory structures)
- Frontend patterns (API call patterns, search paths)
- Tracing configuration (depth, module filtering)

## Adapting Examples for Your Project

Most configs are modular - you can:
1. Mix patterns from different examples
2. Add new route decorator patterns specific to your plugins/middleware
3. Add regex patterns for your custom API call patterns
4. Adjust file glob patterns to match your directory structure

See `../README.md` for full documentation on all configurable options.

## Using Examples

Copy an example configuration to your project root as `mcp_config.json` and customize the patterns for your specific codebase.

```bash
cp examples/fastapi_react.json my_project/mcp_config.json
```

Then edit to match your actual route decorators, API call patterns, and DI patterns.
