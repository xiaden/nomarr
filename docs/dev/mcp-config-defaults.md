# MCP DevTools Default Configuration Strategy

## Philosophy

Tools should "just work" for the 80% use case (FastAPI + React/Vue) with **zero configuration**, while allowing full customization for edge cases.

## Default Behavior

### When No Config File Exists

1. **Auto-detect framework:**
   - Backend: Check for `fastapi`, `flask`, `django` in requirements.txt or imports
   - Frontend: Check for `package.json` dependencies (react, vue, svelte)

2. **Use sensible defaults:**
   - FastAPI: `@router.get/post/put/patch/delete`, `@app.*`
   - Flask: `@app.route`, `@blueprint.route`
   - Django: Search `urls.py` for `path()` calls
   - React: `api.get(`, `fetch(`, `axios.*(`
   - Vue: `$http`, `axios`, `fetch`

3. **Search common paths:**
   - Backend: Root level `*.py`, `app/**/*.py`, `src/**/*.py`, `api/**/*.py`
   - Frontend: `src/**/*.{ts,tsx,js,jsx}`, `components/**/*`, `pages/**/*`

### Config File Discovery

Search order (stop at first found):
1. `mcp_config.json` in workspace root
2. `.mcp/config.json` in workspace root
3. `pyproject.toml` `[tool.mcp]` section
4. Use defaults

## Override Strategy

Config values **merge** with defaults:
- Arrays are **replaced** (not merged) - explicit control
- Objects are **deep merged** - partial overrides allowed
- `null` disables a feature

Example:
```json
{
  "backend": {
    "routes": {
      "decorators": ["@my_custom_route"]  // Replaces entire default list
    }
  }
}
```

## Framework Presets

### FastAPI + React (Default)
```json
{
  "backend": { "framework": "fastapi" },
  "frontend": { "framework": "react" }
  // All other fields use defaults
}
```

### Flask + Vue
```json
{
  "backend": {
    "framework": "flask",
    "routes": {
      "decorators": ["@app.route", "@blueprint.route", "@bp.route"]
    }
  },
  "frontend": {
    "framework": "vue",
    "api_calls": {
      "patterns": ["$http.get(", "$http.post(", "axios.get(", "axios.post("]
    }
  }
}
```

### Django + Svelte
```json
{
  "backend": {
    "framework": "django",
    "routes": {
      "decorators": ["path("],
      "search_paths": ["**/urls.py"]
    }
  },
  "frontend": {
    "framework": "svelte",
    "api_calls": {
      "patterns": ["fetch(", "get(", "post("]
    }
  }
}
```

## Validation Rules

1. **Fail fast on invalid config** - don't silently ignore
2. **Warn on unused keys** - typos are common
3. **Validate paths exist** - catch config errors early
4. **Suggest fixes** - "Did you mean `decorators` instead of `decorator`?"

## Migration Path

For tools currently hardcoded:
1. Extract hardcoded values to `DEFAULT_CONFIG` constant
2. Load user config, merge with defaults
3. Pass merged config to tool functions
4. Tool reads from config, never hardcoded

Example:
```python
# Before
ROUTE_DECORATORS = ["@router.get", "@router.post"]

# After
DEFAULT_CONFIG = {
    "backend": {"routes": {"decorators": ["@router.get", "@router.post"]}}
}

config = load_config()  # Returns merged config
decorators = config["backend"]["routes"]["decorators"]
```
