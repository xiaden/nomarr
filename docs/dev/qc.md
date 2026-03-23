# Code Quality Control (QC) System

**Systematic Process for Auditing and Maintaining Code Quality**

---

## Overview

The QC system provides **automated and manual checks** to maintain code quality across Nomarr. This includes:

- Naming conventions
- Type safety
- Architecture boundaries
- Test coverage
- Documentation
- Security

**Goal:** Catch issues early, maintain clean architecture, prevent technical debt.

---

## Primary QC Tool

**`lint_project_backend`** is the single entry point for all Python code quality checks. It runs:

- **ruff** — Linting and formatting
- **mypy** — Static type checking
- **import-linter** — Layer boundary enforcement (with `check_all=True`)

```python
# Via MCP tool (preferred)
lint_project_backend()                              # Lint git-modified files only
lint_project_backend(path="nomarr/services")        # Lint a specific path
lint_project_backend(check_all=True)                # Full lint + import-linter contracts
```

**Frontend QC:**
```python
lint_project_frontend()  # Runs ESLint + TypeScript
```

Zero errors is the only acceptable state. If `lint_project_backend` reports errors, fix them before moving on.

---

## QC Categories

### 1. Code Standards

**Checks:**
- [ ] Naming conventions follow [naming.md](naming.md)
- [ ] Type hints present and correct (`mypy`)
- [ ] Docstrings for all public functions/classes
- [ ] Import organization (stdlib → third-party → local)
- [ ] No unused imports/variables (`ruff`)

**Tools:**
- `ruff check .` — Linting
- `mypy .` — Type checking
- `import-linter` — Layer boundary enforcement

### 2. Architecture & Design

**Checks:**
- [ ] Layer boundaries respected (see [architecture.md](architecture.md))
- [ ] No circular dependencies
- [ ] Business logic in workflows/components, not services
- [ ] Database access only through persistence layer and components
- [ ] Proper dependency flow: interfaces → services → workflows → components → persistence/helpers

**Tools:**
- `import-linter` — Enforce layer boundaries (run via `lint_project_backend(check_all=True)`)
- `trace_module_calls` / `trace_project_endpoint` — MCP tools to trace call chains

**Layer rules:**
- Interfaces may import services only
- Services may import workflows and components
- Workflows may import components and other workflows
- Components may import persistence and helpers
- Persistence may import helpers only
- Helpers may not import any `nomarr.*` modules

### 3. Error Handling

**Checks:**
- [ ] All file operations have try/except
- [ ] Database operations have error handling
- [ ] HTTP endpoints return proper status codes
- [ ] CLI commands handle failures gracefully
- [ ] Error messages are user-friendly (not stack traces)

**Patterns:**
```python
# ✅ Good
try:
    result = process_file(path)
except FileNotFoundError:
    return {"error": f"File not found: {path}"}
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return {"error": "Processing failed"}

# ❌ Bad
result = process_file(path)  # May crash entire service
```

### 4. Testing Coverage

**Checks:**
- [ ] Unit tests for business logic
- [ ] Integration tests for system flows
- [ ] Edge cases tested (empty, null, invalid)
- [ ] Error paths tested
- [ ] Test fixtures available

**Tools:**
- `pytest tests/ -v` — Run tests
- `pytest --cov=nomarr --cov-report=html` — Coverage report

**Targets:**
- Overall coverage > 80%
- Critical paths (processing, calibration) > 90%
- Interfaces (API, CLI) > 70%

### 5. Documentation

**Checks:**
- [ ] User documentation up to date (see [../user/](../user/))
- [ ] Developer documentation up to date (see [../dev/](../dev/))
- [ ] Config options explained
- [ ] Code comments for complex logic

**Locations:**
- `docs/user/` — User-facing documentation
- `docs/dev/` — Developer documentation
- Docstrings — In-code documentation

### 6. Security

**Checks:**
- [ ] Authentication required where needed
- [ ] No hardcoded secrets/keys
- [ ] Input validation on all endpoints
- [ ] File path validation (no directory traversal)
- [ ] Session secrets not in version control

**Patterns:**
```python
# ✅ Good - AQL parameterized query
db.aql.execute(
    "FOR doc IN library_files FILTER doc._key == @key RETURN doc",
    bind_vars={"key": file_key}
)

# ✅ Good - path validation
if not path.startswith(library_path):
    raise ValueError("Invalid path")
```

### 7. Performance

**Checks:**
- [ ] No N+1 queries
- [ ] ArangoDB indexes on queried fields
- [ ] ONNX model cache working correctly
- [ ] No blocking operations in async code
- [ ] Resource cleanup (file handles, connections)

### 8. Configuration

**Checks:**
- [ ] All settings read via `ConfigService` (never at import time)
- [ ] Sensible defaults
- [ ] Config validation on startup
- [ ] Deprecated settings marked

---

## QC Workflow

### Daily (Before Commit)

```bash
# Quick automated checks (5-10 seconds)
ruff check .
ruff format --check .
import-linter

# Or via MCP tool
lint_project_backend(check_all=True)
```

### Per-Change

After editing any Python file, run:
```python
lint_project_backend(path="nomarr/services")  # or the specific path you changed
```

### Full Audit

```bash
# Complete checks (in Docker for ML dependencies)
docker exec nomarr mypy nomarr/
docker exec nomarr pytest tests/ -v --cov=nomarr
```

---

## Manual Review Process

### Module Review Checklist

For each Python file:

- [ ] File has module docstring
- [ ] All functions have docstrings
- [ ] Type hints on all function signatures
- [ ] Error handling appropriate for domain
- [ ] No TODO/FIXME comments (or tracked in issues)
- [ ] Logging appropriate (no print statements)
- [ ] Constants defined at module level
- [ ] No magic numbers/strings
- [ ] Resource cleanup (context managers)
- [ ] Tests exist for this module

### Priority Modules (Review First)

**1. Core Processing:**
- `nomarr/workflows/processing/` — Audio processing workflows
- `nomarr/components/ml/` — ONNX inference, audio preprocessing
- `nomarr/components/tagging/` — Tag extraction and aggregation

**2. Services:**
- `nomarr/services/domain/library_svc/` — Library management
- `nomarr/services/domain/calibration_svc.py` — Calibration
- `nomarr/services/domain/tagging_svc.py` — Tagging operations
- `nomarr/services/infrastructure/worker_system_svc.py` — Worker lifecycle

**3. Persistence Layer:**
- `nomarr/persistence/db.py` — Database facade
- `nomarr/persistence/database/` — AQL operations modules

**4. API Layer:**
- `nomarr/interfaces/api/` — FastAPI routes and auth

**5. CLI Layer:**
- `nomarr/interfaces/cli/` — CLI commands

---

## QC Reports

### Report Structure

```
qc_reports/
├── YYYY-MM-DD_HHMMSS_qc_report.txt  # Timestamped QC output
└── ...                               # Historical reports
```

---

## ML Dependencies and QC

### The Problem

Some QC tools (mypy, vulture) need to import modules, which may trigger ML dependency loading:

- ONNX Runtime models
- Essentia audio I/O
- GPU initialization

This can be slow on development machines without GPU.

### The Solution

**On development machine (fast):**
```bash
# No ML dependencies needed
ruff check .
import-linter
lint_project_backend(check_all=True)
```

**In Docker container (complete):**
```bash
# With ML dependencies
docker exec nomarr mypy nomarr/
docker exec nomarr pytest tests/
```

---

## Tool Reference

### MCP Tools (Preferred)

| Tool | Purpose |
|------|---------|
| `lint_project_backend()` | Run ruff + mypy (+ import-linter with `check_all`) |
| `lint_project_frontend()` | Run ESLint + TypeScript |
| `read_module_api(module)` | Inspect module's public API without reading full file |
| `locate_module_symbol(name)` | Find where a symbol is defined |
| `trace_module_calls(fn)` | Follow call chains from entry points |
| `trace_project_endpoint(ep)` | Trace FastAPI route through DI layers |

### CLI Tools

**Always available (no ML deps):**

| Tool | Purpose |
|------|---------|
| `ruff` | Fast linter and formatter |
| `import-linter` | Architecture boundary enforcer |
| `radon` | Complexity metrics |
| `interrogate` | Docstring coverage |

**Requires Docker (ML deps):**

| Tool | Purpose |
|------|---------|
| `mypy` | Static type checking |
| `bandit` | Security scanner |
| `vulture` | Dead code detector |
| `pytest` | Test runner with coverage |

### Installing CLI Tools

```bash
pip install ruff radon interrogate import-linter
```

---

## QC Metrics

### Track Over Time

**Code Quality:**
- Linting errors: Target = 0
- Type coverage: Target > 95%
- Docstring coverage: Target > 90%

**Architecture:**
- Import boundary violations: Target = 0
- Circular dependencies: Target = 0
- Average complexity: Target < 10

**Testing:**
- Test coverage: Target > 80%
- Critical path coverage: Target > 90%
- Failed tests: Target = 0

---

## Related Documentation

- [Naming Standards](naming.md) — Naming conventions
- [Architecture](architecture.md) — System design and layer rules
- [Domains](domains.md) — Domain catalog

---

## Summary

**QC is systematic:**
1. Run `lint_project_backend` after every change
2. Manual review of changed code
3. Track metrics over time
4. Fix issues before they accumulate

**QC is fast:**
- Per-change checks: 5–10 seconds via `lint_project_backend`
- Full Docker checks: 2–3 minutes

**QC prevents:**
- Architecture violations
- Security issues
- Performance regressions
- Technical debt accumulation
- Inconsistent code style

**Goal:** Maintain high code quality without slowing development.
