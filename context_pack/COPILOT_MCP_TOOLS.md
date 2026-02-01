# Nomarr MCP Tools Reference

Copilot has access to these tools via the `nomarr-dev` MCP server.
All outputs are JSON. Examples are from actual tool runs.

---

## Navigation Tools

### `list_dir(folder?)`
Smart directory listing with filtering. Excludes .venv, node_modules, __pycache__.

```json
{
  "path": "nomarr/components",
  "structure": {
    "analytics/": { "__init__.py": 1, "analytics_comp.py": 1 },
    "library/": { "__init__.py": 1, "file_batch_scanner_comp.py": 1, "..." },
    "ml/": { "__init__.py": 1, "chromaprint_comp.py": 1, "..." }
  }
}
```

### `discover_api(module_name)`
Discover module's exported API (classes, functions, signatures).

```json
{
  "module": "nomarr.helpers.exceptions",
  "exports": ["NomarrError", "ConfigurationError", "LibraryNotFoundError"],
  "classes": [
    { "name": "NomarrError", "bases": ["Exception"], "methods": ["__init__"] }
  ],
  "functions": []
}
```

### `locate_symbol(symbol_name)`
Find where a symbol is defined across the codebase.

```json
{
  "query": "LibraryService",
  "matches": [
    {
      "file": "nomarr/services/domain/library_svc/__init__.py",
      "line": 26,
      "kind": "Class",
      "qualified_name": "nomarr.services.domain.library_svc.LibraryService"
    }
  ],
  "total_matches": 1
}
```

### `get_source(qualified_name)`
Get source code of a specific function/class.

```json
{
  "name": "nomarr.helpers.exceptions.NomarrError",
  "kind": "Class",
  "file": "nomarr/helpers/exceptions.py",
  "start_line": 8,
  "end_line": 15,
  "source": "class NomarrError(Exception):\n    \"\"\"Base exception...\"\"\"\n    ..."
}
```

### `symbol_at_line(file_path, line_number)`
Get symbol context at a specific line (useful for error debugging).

```json
{
  "qualified_name": "NomarrError.__init__",
  "kind": "Function",
  "start_line": 12,
  "end_line": 15,
  "source": "def __init__(self, message: str):\n    ...",
  "file": "nomarr/helpers/exceptions.py"
}
```

### `search_text(pattern, folder?)`
Regex pattern search in files.

```json
{
  "pattern": "NomarrError",
  "folder": "nomarr/helpers",
  "matches": [
    { "file": "nomarr/helpers/exceptions.py", "line": 8, "text": "class NomarrError(Exception):" }
  ],
  "total": 3
}
```

---

## File Reading Tools

### `read_file(file_path, start_line, end_line)`
Read line range from file. Max 100 lines per call.

```json
{
  "path": "nomarr/helpers/exceptions.py",
  "content": "\"\"\"Nomarr exceptions.\"\"\"\n\nclass NomarrError(Exception):...",
  "start": 1,
  "end": 20
}
```

### `read_line(file_path, line_number)`
Quick single-line read with minimal context.

```json
{
  "file": "nomarr/helpers/exceptions.py",
  "line": 10,
  "content": "    \"\"\"Base exception for Nomarr errors.\"\"\""
}
```

---

## API Discovery Tools

### `list_routes()`
List all API routes via static analysis. See `api_routes.json` for full output.

```json
{
  "total": 65,
  "summary": { "integration": 5, "web": 60, "other": 0 },
  "routes": [
    { "method": "GET", "path": "/api/web/libraries", "function": "list_libraries", "file": "...", "line": 57 }
  ]
}
```

### `check_api_coverage(filter_mode?)`
Check which backend APIs are used by frontend. See `api_coverage.json` for full output.

```json
{
  "stats": { "total": 65, "used": 42, "unused": 23, "coverage_pct": 64.6 },
  "endpoints": [
    { "method": "GET", "path": "/api/web/libraries", "used": true, "locations": [...] }
  ]
}
```

---

## Linting Tools

### `lint_backend(path?, check_all?)`
Run ruff, mypy, import-linter on Python code.

```json
{
  "status": "clean",
  "ruff": { "errors": 0 },
  "mypy": { "errors": 0 },
  "import_linter": { "errors": 0 }
}
```

### `lint_frontend()`
Run ESLint and TypeScript check on frontend.

```json
{
  "status": "clean",
  "eslint": { "errors": 0, "warnings": 2 },
  "typescript": { "errors": 0 }
}
```

---

## Task Plan Tools

### `read_plan(plan_name)`
Parse task plan markdown into structured JSON.

```json
{
  "plan": "TASK-component-atomization",
  "phases": [
    { "name": "Phase 1", "steps": [...], "complete": false }
  ],
  "progress": { "total_steps": 12, "completed": 4 }
}
```

### `get_steps(plan_name, phase?)`
Get steps for a specific phase.

```json
{
  "phase": "Phase 1",
  "steps": [
    { "text": "Create test file", "complete": true },
    { "text": "Run tests", "complete": false }
  ]
}
```

### `complete_step(plan_name, step_text, annotation?)`
Mark a step complete in the plan file.

```json
{
  "success": true,
  "step": "Create test file",
  "annotation": "Done via test",
  "next_step": "Run tests"
}
```

---

## Editing Tools

### `atomic_replace(file_path, replacements[])`
Multiple string replacements in single write. Prevents formatter race conditions.

```json
{
  "success": true,
  "file": "test.py",
  "replacements_made": 2
}
```

### `move_text(file_path, start_line, end_line, target_line)`
Move lines within a file.

```json
{
  "success": true,
  "moved": { "from": [1, 2], "to": 7 }
}
```

---

## Broken Tools (Need Fixes)

### `trace_calls(function_name)` ⚠️
**Status: BROKEN** - Cannot resolve function locations, returns null file/line.

Expected: Trace call chain from function through codebase.

### `trace_endpoint(qualified_name)` ⚠️
**Status: BROKEN** - Module path resolution fails.

Expected: Trace API endpoint through FastAPI DI to service methods.

---

## Usage Notes

1. **Prefer semantic tools** over `read_file` for Python code
2. **discover_api first** to understand module shape before reading source
3. **locate_symbol** to find definitions when you know the name
4. **lint_backend** to validate changes before committing
5. **Full API data** in `api_routes.json` and `api_coverage.json`
