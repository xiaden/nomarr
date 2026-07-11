---
name: nomarr-testing
description: Testing conventions for the Nomarr project — pytest backend tests (unit/integration/e2e markers, fixtures, mocking patterns), Vitest frontend tests (component/hook/API client), and Playwright E2E tests (fixtures, selectors, Docker environment). Use when writing, running, or reviewing tests in tests/, frontend/src/**/*.test.*, or e2e/.
---

# Nomarr Testing Conventions

**Purpose:** Define how to write, organize, and run tests across all three test suites in the Nomarr codebase.

---

## When to Use

**Trigger conditions:**
- Writing or editing tests in `tests/` (pytest), `frontend/src/**/*.test.*` (Vitest), or `e2e/` (Playwright)
- Running test suites or debugging test failures
- Choosing which test type to write for a given scenario
- Setting up test fixtures or mocking patterns

**Do NOT use for:**
- Layer architecture conventions (use `nomarr-layers`)
- Integration with the live Docker environment (use `docker`)
- Code quality / linting tool guidance (covered per-layer in `nomarr-layers`)

---

## Test Suite Overview

| Suite | Tool | Location | Runs Against | Speed |
|-------|------|----------|-------------|-------|
| **Backend** | pytest | `tests/` (unit + integration directories) | Python code directly or via mocks | ms to <1s |
| **Frontend** | Vitest + RTL | `frontend/src/**/*.test.{ts,tsx}` | jsdom environment | ms |
| **E2E** | Playwright | `e2e/*.spec.ts` | Docker containers (full stack) | seconds |

---

## When to Use Which Test Type

| Test This With... | E2E (Playwright) | Backend (pytest) | Frontend (Vitest) |
|---|---|---|---|
| Login flow works end-to-end | ✅ | | |
| API returns correct JSON shape | | ✅ | |
| Component renders correctly for given props | | | ✅ |
| Navigation between pages works | ✅ | | |
| Business logic computes correct result | | ✅ | |
| Button click triggers correct API call | ✅ | | |
| Form validation shows error messages | | | ✅ |
| Full library scan → ML tagging pipeline | ✅ | | |
| Utility function handles edge cases | | ✅ | ✅ |

---

## Quick Reference

### Backend (pytest)

```bash
# Run all unit tests
pytest -m unit

# Run a specific test file
pytest tests/unit/helpers/test_time_helper.py

# Run a specific test
pytest tests/unit/helpers/test_time_helper.py::TestNowMs::test_now_ms_returns_milliseconds_type

# Fast local dev (skip expensive)
pytest -m "unit and not slow and not requires_models"

# Pre-commit (unit + integration, skip expensive)
pytest -m "(unit or integration) and not slow and not container_only"
```

### Frontend (Vitest)

```powershell
# Run all frontend tests
Push-Location frontend; npm test; Pop-Location

# Watch mode
Push-Location frontend; npm run test:watch; Pop-Location

# Run a specific test file
Push-Location frontend; npx vitest run src/features/calibration/CalibrationPage.test.tsx; Pop-Location
```

### E2E (Playwright)

Run from `e2e/` directory:

```powershell
# Run all E2E tests
npx playwright test

# Run a specific spec
npx playwright test smoke.spec.ts

# Headed mode (see the browser)
npx playwright test --headed

# Debug a specific test
npx playwright test smoke.spec.ts --debug
```

---

## Layer Reference Files

| Test Suite | Reference | Summary |
|------------|-----------|---------|
| Backend (pytest) | [`references/backend.md`](references/backend.md) | Pytest markers, fixtures, mocking patterns, naming conventions |
| Frontend (Vitest) | [`references/frontend.md`](references/frontend.md) | Vitest + React Testing Library, hooks, components, API client |
| E2E (Playwright) | [`references/e2e.md`](references/e2e.md) | Docker environment, fixtures, selectors, timing, debugging |

---

## Cross-Suite Anti-Patterns

```python
# ❌ Testing implementation details
def test_calls_db_twice():
    mock_db.some_method.assert_called_exactly(2)  # Brittle

# ✅ Testing behavior
def test_returns_all_pending_files():
    result = get_pending(mock_db)
    assert len(result) == 3
```

```typescript
// ❌ Snapshot testing everything
expect(container).toMatchSnapshot();

// ✅ Targeted assertions on what matters
expect(screen.getByText('12 of 12 heads')).toBeInTheDocument();
```

```typescript
// ❌ Hardcoded URLs in E2E
await page.goto('http://localhost:8356/calibration');

// ✅ Use baseURL from config
await page.goto('/calibration');
```

---

## Validation Checklist

Before committing test code:
- [ ] Backend tests have at least one type marker (`unit`, `integration`, or `e2e`)
- [ ] Backend tests are in the correct subdirectory (mirrors `nomarr/` structure)
- [ ] Frontend tests are co-located next to the source file
- [ ] E2E tests use auth fixture for authenticated pages
- [ ] No hardcoded URLs in E2E (use `baseURL`)
- [ ] All relevant test suites pass locally

---

## Related Skills

- `nomarr-layers` — Architecture layer conventions
- `docker` — Docker development environment (required for E2E tests)
- `embedding-research` — Embedding research pipeline (has its own test protocols)
