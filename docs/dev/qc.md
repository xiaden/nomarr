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

## QC Categories

### 1. Code Standards

**Checks:**
- [ ] Naming conventions follow [naming.md](naming.md)
- [ ] Type hints present and correct (`mypy`)
- [ ] Docstrings for all public functions/classes
- [ ] Import organization (stdlib → third-party → local)
- [ ] No unused imports/variables (`ruff`)

**Tools:**
- `scripts/check_naming.py` - Naming violations
- `ruff check .` - Linting
- `mypy .` - Type checking
- `interrogate nomarr/` - Docstring coverage

### 2. Architecture & Design

**Checks:**
- [ ] Layer boundaries respected (see [architecture.md](architecture.md))
- [ ] No circular dependencies
- [ ] Business logic in workflows, not services
- [ ] Database access through persistence layer only
- [ ] Proper dependency flow: interfaces → services → workflows → components → persistence → helpers

**Tools:**
- `import-linter` - Enforce layer boundaries
- `scripts/discover_import_chains.py` - Detect circular imports
- Manual review

**Layer rules:**
- Interfaces may import services only
- Services may import workflows, persistence, components
- Workflows may import components, persistence, helpers
- Components may import persistence, helpers
- Persistence may import helpers only
- Helpers may not import any nomarr.* modules

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
- `pytest tests/ -v` - Run tests
- `pytest --cov=nomarr --cov-report=html` - Coverage report

**Targets:**
- Overall coverage > 80%
- Critical paths (processing, calibration) > 90%
- Interfaces (API, CLI) > 70%

### 5. Documentation

**Checks:**
- [ ] User documentation up to date (see [../user/](../user/))
- [ ] Developer documentation up to date (see [../dev/](../dev/))
- [ ] API endpoints documented in [../user/api_reference.md](../user/api_reference.md)
- [ ] Config options explained
- [ ] Code comments for complex logic

**Locations:**
- `docs/user/` - User-facing documentation
- `docs/dev/` - Developer documentation
- `docs/design/` - Design documents and roadmaps
- Docstrings - In-code documentation

### 6. Security

**Checks:**
- [ ] Authentication required where needed
- [ ] No hardcoded secrets/keys
- [ ] Input validation on all endpoints
- [ ] SQL injection protection (parameterized queries)
- [ ] File path validation (no directory traversal)
- [ ] Session secrets not in version control

**Patterns:**
```python
# ✅ Good - parameterized query
cursor.execute("SELECT * FROM queue WHERE id = ?", (job_id,))

# ❌ Bad - SQL injection risk
cursor.execute(f"SELECT * FROM queue WHERE id = {job_id}")

# ✅ Good - path validation
if not path.startswith(library_path):
    raise ValueError("Invalid path")

# ❌ Bad - directory traversal risk
open(path, 'r')  # No validation
```

### 7. Performance

**Checks:**
- [ ] No N+1 queries
- [ ] Database indices on queried columns
- [ ] Model cache working correctly
- [ ] No blocking operations in async code
- [ ] Resource cleanup (file handles, connections)

**Tools:**
- `radon cc nomarr/ -s` - Cyclomatic complexity
- `radon mi nomarr/ -s` - Maintainability index
- Manual profiling with `cProfile`

### 8. Configuration

**Checks:**
- [ ] All settings in `config.yaml`
- [ ] Sensible defaults
- [ ] Environment variable overrides work
- [ ] Config validation on startup
- [ ] Deprecated settings marked

**Pattern:**
```python
# ✅ Good - validated config
class ProcessorConfig:
    workers: int = 2
    batch_size: int = 8
    timeout: int = 300
    
    def __post_init__(self):
        if self.workers < 1:
            raise ValueError("workers must be >= 1")
```

---

## QC Scripts

### Automated Checks

Run these to catch issues automatically:

```bash
# 1. Naming conventions
python scripts/check_naming.py

# 2. Linting and formatting
ruff check .
ruff format --check .

# 3. Type checking (requires running environment)
docker exec nomarr mypy nomarr/

# 4. Import boundaries
import-linter

# 5. Complexity metrics
radon cc nomarr/ -s -a

# 6. Docstring coverage
interrogate nomarr/ -vv

# 7. Security scan
docker exec nomarr bandit -r nomarr/

# 8. Dead code detection
docker exec nomarr vulture nomarr/
```

### Quick QC Check

**Fast checks (no ML dependencies):**
```bash
#!/bin/bash
# scripts/qc_quick.sh

echo "Running quick QC checks..."

echo "\n1. Naming conventions..."
python scripts/check_naming.py

echo "\n2. Linting..."
ruff check .

echo "\n3. Formatting..."
ruff format --check .

echo "\n4. Import boundaries..."
import-linter

echo "\nQuick QC complete."
```

### Full QC Check

**Complete checks (in Docker with ML dependencies):**
```bash
#!/bin/bash
# scripts/qc_full.sh

echo "Running full QC checks..."

# Fast checks
./scripts/qc_quick.sh

# ML-dependent checks
echo "\n5. Type checking..."
docker exec nomarr mypy nomarr/

echo "\n6. Security scan..."
docker exec nomarr bandit -r nomarr/

echo "\n7. Dead code..."
docker exec nomarr vulture nomarr/

echo "\n8. Running tests..."
docker exec nomarr pytest tests/ -v

echo "\nFull QC complete."
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
- `nomarr/workflows/processing/` - Audio processing workflows
- `nomarr/components/ml/inference.py` - ML model execution
- `nomarr/components/tagging/` - Tag extraction and aggregation

**2. Services (Business Logic):**
- `nomarr/services/processing_service.py`
- `nomarr/services/queue_service.py`
- `nomarr/services/library_service.py`
- `nomarr/services/calibration_service.py`

**3. Persistence Layer:**
- `nomarr/persistence/db.py` - Database connection
- `nomarr/persistence/database/*_operations.py` - Table operations

**4. API Layer:**
- `nomarr/interfaces/api/app.py` - Main API setup
- `nomarr/interfaces/api/routes/` - API endpoints
- `nomarr/interfaces/api/auth.py` - Authentication

**5. CLI Layer:**
- `nomarr/interfaces/cli/main.py` - CLI dispatcher
- `nomarr/interfaces/cli/commands/` - CLI commands

---

## QC Workflow

### Full Codebase Audit

```bash
# Phase 1: Automated checks
mkdir -p qc_reports
python scripts/check_naming.py > qc_reports/naming.txt
ruff check . > qc_reports/linting.txt
docker exec nomarr pytest tests/ --cov=nomarr --cov-report=html

# Phase 2: Module-by-module review
# Use checklist above for each module
python scripts/review_module.py nomarr/services/ > qc_reports/services_review.txt
```

### Per-Module Review

```bash
# Review specific module
python scripts/review_module.py nomarr/services/queue_service.py
```

**Output includes:**
- Complexity metrics
- Missing docstrings
- Type hint coverage
- Import issues
- TODOs/FIXMEs

---

## QC Reports

### Report Structure

```
qc_reports/
├── 2025-12-05_naming.txt           # Naming violations
├── 2025-12-05_linting.txt          # Ruff output
├── 2025-12-05_complexity.txt       # Radon complexity
├── 2025-12-05_coverage.html        # Test coverage
├── 2025-12-05_manual_review.md     # Manual findings
└── action_items.md                 # Issues to fix
```

### Action Item Template

```markdown
## [Module] Issue Title

**Severity:** High / Medium / Low
**Category:** Code Standards / Architecture / Error Handling / Testing / Documentation / Security / Performance / Configuration
**File:** path/to/file.py
**Lines:** 123-145

**Issue:**
Description of what's wrong

**Impact:**
Why this matters (security, bugs, maintainability)

**Fix:**
Proposed solution

**Priority:** P0 (critical) / P1 (important) / P2 (nice to have)

**Estimated Effort:** Hours or story points

**Assigned To:** (if applicable)
```

---

## ML Dependencies and QC

### The Problem

Some QC tools (mypy, vulture, bandit) need to import modules, which triggers ML dependency loading:

- essentia-tensorflow (requires CUDA)
- TensorFlow models (~2GB)
- GPU initialization (~30s)

This makes local development slow on Windows.

### The Solution

**On development machine (fast):**
```bash
# No ML dependencies
python scripts/check_naming.py
ruff check .
import-linter
radon cc nomarr/ -s
```

**In Docker container (complete):**
```bash
# With ML dependencies
docker exec nomarr mypy nomarr/
docker exec nomarr bandit -r nomarr/
docker exec nomarr vulture nomarr/
docker exec nomarr pytest tests/
```

### Practical QC Workflow

**Daily (before commit):**
```bash
./scripts/qc_quick.sh  # 5-10 seconds
```

**Weekly:**
```bash
./scripts/qc_full.sh   # 2-3 minutes in Docker
```

**Before release:**
- Full automated QC
- Manual review of changed modules
- Update documentation
- Review test coverage

---

## Ongoing QC

### Pre-Commit Checks

**Recommended pre-commit hook** (`.git/hooks/pre-commit`):

```bash
#!/bin/bash
echo "Running pre-commit QC checks..."

# Fast checks only
python scripts/check_naming.py || exit 1
ruff check . || exit 1
ruff format --check . || exit 1

echo "Pre-commit checks passed."
```

Make executable:
```bash
chmod +x .git/hooks/pre-commit
```

### Weekly Review

- [ ] Run full automated QC suite
- [ ] Review one major module thoroughly
- [ ] Update documentation if needed
- [ ] Address P0/P1 action items
- [ ] Update QC metrics

### Monthly Audit

- [ ] Full codebase review
- [ ] Update QC checklist if needed
- [ ] Review test coverage gaps
- [ ] Check for tech debt accumulation
- [ ] Update dependency versions

---

## QC Metrics

### Track Over Time

**Code Quality:**
- Naming violations: Target = 0
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

**Maintenance:**
- Open action items: Target < 10
- Critical issues: Target = 0
- TODOs in code: Target < 20

### Visualize Metrics

**Generate report:**
```bash
python scripts/qc_metrics.py > qc_reports/metrics.json
```

**Track in spreadsheet or dashboard.**

---

## Tool Reference

### Available Tools

**Always available (no ML deps):**
1. `ruff` - Fast linter and formatter
2. `check_naming.py` - Naming convention checker
3. `import-linter` - Architecture boundary enforcer
4. `radon` - Complexity metrics
5. `interrogate` - Docstring coverage
6. `wily` - Code metrics over time
7. `discover_api.py` - Module API inspection (see below)

**Requires Docker (ML deps):**
1. `mypy` - Static type checking
2. `bandit` - Security scanner
3. `vulture` - Dead code detector
4. `pytest` - Test runner with coverage

### API Discovery Tools

Nomarr provides utility scripts to explore module APIs without reading full source files.

#### discover_api.py

Shows the public API of any Python module.

**Usage:**
```bash
python scripts/discover_api.py <module.path>
```

**Examples:**
```bash
# Discover database operations
python scripts/discover_api.py nomarr.persistence.db

# Discover workflow functions
python scripts/discover_api.py nomarr.workflows.processing.process_file

# Discover ML inference API
python scripts/discover_api.py nomarr.components.ml.inference
```

**Output includes:**
- Functions with parameters, return types, and docstrings
- Classes with methods and docstrings
- Module-level constants

**Important:** Do NOT use the `--summary` flag - it only shows names without signatures.

**Use cases:**
- Verify function signatures before calling them
- Update documentation to reflect actual APIs
- See what needs to be mocked in tests
- Avoid guessing or inventing function names

#### discover_imports.py

Shows what a module imports and uses.

**Usage:**
```bash
python scripts/discover_imports.py <module.path>
```

**Examples:**
```bash
# Check workflow dependencies
python scripts/discover_imports.py nomarr.workflows.processing.process_file

# Check service dependencies
python scripts/discover_imports.py nomarr.services.processing_service
```

**Output includes:**
- Direct imports (`import X`)
- From imports (`from X import Y`)
- Function calls within the module
- Class instantiations

**Use cases:**
- Identify what to mock when writing tests
- Verify architecture boundaries (workflows shouldn't import services)
- Understand module dependencies

**Technical notes:**
- Both tools automatically mock ML dependencies (essentia, tensorflow)
- Safe to run on development machines without GPU
- Static analysis only (does not execute code)

### Installing Tools

```bash
# Development machine (no ML deps)
pip install ruff radon interrogate wily import-linter

# Docker container (with ML deps)
# Already installed in nomarr Docker image
```

---

## Related Documentation

- [Naming Standards](naming.md) - Naming conventions
- [Architecture](architecture.md) - System design and layer rules
- [Services](services.md) - Service patterns
- [Testing](../../tests/TEST_STRUCTURE.md) - Test organization

---

## Summary

**QC is systematic:**
1. Run automated checks regularly
2. Manual review of changed code
3. Track metrics over time
4. Fix issues before they accumulate

**QC is fast:**
- Quick checks: 5-10 seconds (pre-commit)
- Full checks: 2-3 minutes (Docker)
- Weekly reviews: 30 minutes

**QC prevents:**
- Architecture violations
- Security issues
- Performance regressions
- Technical debt accumulation
- Inconsistent code style

**Goal:** Maintain high code quality without slowing development.
