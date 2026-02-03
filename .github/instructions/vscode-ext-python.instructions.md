---
applyTo: vscode-ext/**/src/python/**
---

# Python Bridge (TS → Python tools)

This folder contains the interop layer between TypeScript extension code and Python tools.

## Strategy
- Subprocess per call, JSON-over-stdio.
- No persistent protocol/state in this layer.

## JSON Safety
- Python stdout may contain noise; extract the final JSON payload deterministically.
- If no parseable JSON exists => FAILED(PYTHON_ERROR) with captured stdout/stderr.

## Environment
- Resolve python executable deterministically (venv first, then fallback only if explicit).
- Set PYTHONPATH to workspace root so `nomarr.*` imports work.

## Results
- Never throw; return structured results with `stderr` included when present.
- Do not retry here; retries belong to orchestrators.

---

## Reference (non-prescriptive)

### Python Tools Called
- `scripts/mcp/tools/lint_project_backend.py` - Ruff + mypy
- `scripts/mcp/tools/lint_project_frontend.py` - ESLint + TypeScript

### Python Path
```typescript
const venvPython = path.join(workspaceRoot, '.venv', 'Scripts', 'python.exe');
env: { PYTHONPATH: workspaceRoot }
```

### Debugging Checklist
1. ☐ `.venv/Scripts/python.exe` exists
2. ☐ Run Python manually in terminal first
3. ☐ Check `result.stderr` for warnings
