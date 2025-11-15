# Code Quality Control (QC) System

Systematic process for auditing and maintaining code quality across the nomarr codebase.

## QC Categories

### 1. Code Standards

- [ ] Naming conventions (`check_naming.py`)
- [ ] Type hints present and correct
- [ ] Docstrings for all public functions/classes
- [ ] Import organization (stdlib, third-party, local)
- [ ] No unused imports/variables

### 2. Architecture & Design

- [ ] Service layer boundaries respected
- [ ] No circular dependencies
- [ ] Business logic in services, not interfaces
- [ ] Database access through data layer only
- [ ] Proper separation: interfaces → services → core → data

### 3. Error Handling

- [ ] All file operations have try/except
- [ ] Database operations have error handling
- [ ] HTTP endpoints return proper status codes
- [ ] CLI commands handle failures gracefully
- [ ] Error messages are user-friendly (not stack traces)

### 4. Testing Coverage

- [ ] Unit tests for business logic
- [ ] Integration tests for system flows
- [ ] Edge cases tested (empty, null, invalid)
- [ ] Error paths tested
- [ ] Test fixtures available

### 5. Documentation

- [ ] README.md up to date
- [ ] API endpoints documented
- [ ] Config options explained
- [ ] Deployment guide current
- [ ] Code comments for complex logic

### 6. Security

- [ ] Authentication required where needed
- [ ] No hardcoded secrets/keys
- [ ] Input validation on all endpoints
- [ ] SQL injection protection (parameterized queries)
- [ ] File path validation (no directory traversal)

### 7. Performance

- [ ] No N+1 queries
- [ ] Database indices on queried columns
- [ ] Model cache working correctly
- [ ] No blocking operations in async code
- [ ] Resource cleanup (file handles, connections)

### 8. Configuration

- [ ] All settings in config.yaml
- [ ] Sensible defaults
- [ ] Environment variable overrides
- [ ] Config validation on startup
- [ ] Deprecated settings marked

## QC Scripts

### Automated Checks

Run these to catch issues automatically:

```bash
# 1. Naming conventions
python scripts/check_naming.py

# 2. Linting
ruff check .

# 3. Type checking (if mypy configured)
# mypy nomarr/

# 4. Unused code
# vulture nomarr/

# 5. Security issues
# bandit -r nomarr/

# 6. Import organization
python scripts/discover_imports.py
```

### Manual Review Process

For each module/file:

1. **Open the file**
2. **Check against QC categories above**
3. **Document findings** in `QC_FINDINGS.md`
4. **Create issues/tasks** for problems found
5. **Fix high-priority items immediately**

## QC Workflow

### Full Codebase Audit

```bash
# Phase 1: Automated checks
python scripts/check_naming.py > qc_reports/naming.txt
ruff check . > qc_reports/linting.txt
pytest tests/ --cov=nomarr --cov-report=html

# Phase 2: Module-by-module review
# Start with core modules, then services, then interfaces
# Use checklist below for each module
```

### Module Review Checklist

For each Python file:

- [ ] File header docstring present
- [ ] All functions have docstrings
- [ ] Type hints on function signatures
- [ ] Error handling appropriate
- [ ] No TODO/FIXME comments (or tracked)
- [ ] Logging appropriate (not print statements)
- [ ] Constants defined at module level
- [ ] No magic numbers/strings
- [ ] Resource cleanup (context managers)
- [ ] Tests exist for this module

### Priority Modules (Review First)

1. **Core Processing**

   - `nomarr/core/processor.py` - Main audio processing
   - `nomarr/ml/inference.py` - ML model execution
   - `nomarr/tagging/aggregation.py` - Tag rules

2. **Services** (Business Logic)

   - `nomarr/services/processing.py`
   - `nomarr/services/queue.py`
   - `nomarr/services/library.py`
   - `nomarr/services/calibration.py`

3. **Data Layer**

   - `nomarr/data/db.py` - Database schema/queries
   - `nomarr/data/queue.py` - Queue operations

4. **API Layer**

   - `nomarr/interfaces/api/app.py` - Main API
   - `nomarr/interfaces/api/auth.py` - Authentication
   - `nomarr/interfaces/api/endpoints/*.py` - Endpoints

5. **CLI Layer**
   - `nomarr/interfaces/cli/main.py` - CLI dispatcher
   - `nomarr/interfaces/cli/commands/*.py` - Commands

## QC Reports

Store findings in `qc_reports/` directory:

```
qc_reports/
├── 2025-11-15_naming.txt        # Naming violations
├── 2025-11-15_linting.txt       # Ruff output
├── 2025-11-15_coverage.html     # Test coverage
├── 2025-11-15_manual_review.md  # Manual findings
└── action_items.md              # Issues to fix
```

## Action Item Template

When issues are found:

```markdown
## [Module] Issue Title

**Severity:** High / Medium / Low
**Category:** Code Standards / Architecture / Error Handling / etc.
**File:** path/to/file.py
**Lines:** 123-145

**Issue:**
Description of what's wrong

**Impact:**
Why this matters (security, bugs, maintainability)

**Fix:**
Proposed solution

**Priority:** P0 (critical) / P1 (important) / P2 (nice to have)
```

## Ongoing QC

### Pre-Commit Checks

Before committing:

```bash
# Run automated checks
ruff check .
python scripts/check_naming.py

# If changes to tests
pytest tests/ -v
```

### Weekly Review

- [ ] Run full automated QC suite
- [ ] Review one major module thoroughly
- [ ] Update documentation if needed
- [ ] Address P0/P1 action items

### Monthly Audit

- [ ] Full codebase review
- [ ] Update QC checklist if needed
- [ ] Review test coverage
- [ ] Check for tech debt accumulation

## QC Metrics

Track these over time:

- **Naming violations:** Target = 0
- **Linting errors:** Target = 0
- **Test coverage:** Target > 80%
- **Documentation coverage:** Target > 90%
- **Open action items:** Target < 10
- **Critical issues:** Target = 0

## Additional Tools (Optional)

Tools that could enhance QC but have limitations:

### Available Now (No ML Dependencies)

1. **ruff** - Linting and formatting ✅ (already using)
2. **check_naming.py** - Naming conventions ✅ (already using)
3. **radon** - Code complexity metrics
4. **interrogate** - Docstring coverage checker

Install these:

```bash
pip install radon interrogate
```

### Blocked by ML Dependencies

These tools are blocked because essentia-tensorflow isn't available on Windows dev environment:

1. **mypy** - Static type checking

   - Problem: Needs essentia imports to resolve types
   - Workaround: Run in Docker container where essentia is installed
   - Command: `docker exec nomarr python3 -m mypy nomarr/`

2. **vulture** - Dead code detection

   - Problem: Needs to import modules (triggers essentia loading)
   - Workaround: Manual review or run in container

3. **bandit** - Security scanner
   - Problem: Similar import issues
   - Workaround: Run in container for security audits

### Why Not Install Essentia on Windows Dev?

Essentia-tensorflow + TensorFlow + models would trigger ML inference if code is executed, which:

- Takes ~30-60s to load models
- Uses GPU/VRAM (if available)
- Slows down development workflow

**Solution**: Keep dev environment lightweight, run ML-dependent tools in Docker.

### Practical QC Workflow

**On Windows Dev Machine:**

```bash
# Fast checks (no ML deps)
python scripts/check_naming.py
ruff check .
python scripts/review_module.py nomarr/services/
radon cc nomarr/ -s  # Complexity
interrogate nomarr/  # Docstring coverage
```

**In Docker Container:**

```bash
# Full checks (with ML deps)
docker exec nomarr python3 -m mypy nomarr/
docker exec nomarr python3 -m bandit -r nomarr/
docker exec nomarr python3 -m vulture nomarr/
```

## Next Steps

1. Create `qc_reports/` directory
2. Run initial automated checks
3. Create baseline QC report
4. Prioritize and fix critical issues
5. Set up pre-commit hooks
6. Schedule weekly reviews
