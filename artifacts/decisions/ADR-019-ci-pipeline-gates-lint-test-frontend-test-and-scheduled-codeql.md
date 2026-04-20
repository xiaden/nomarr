# ADR-019: CI Pipeline Gates: Lint, Test, Frontend Test, and Scheduled CodeQL

**Status:** Accepted  
**Date:** 2026-04-05  
**Tags:** ci, testing, lint, codeql, security, quality  

## Context

The current `ci.yml` enforces two implicit gates: unit tests (pytest, skipping container/DB/GPU tests) and a frontend build-freshness check. Linting (`ruff`), frontend unit tests (Vitest), and CodeQL static analysis are not CI gates. A `codeql-config.yml` exists but no scheduled workflow drives it. As the two-branch model (ADR-017) makes `main` a quality gate, the set of enforced checks must be explicit and complete.

## Decision

The CI pipeline enforces four mandatory gates, all required to pass before any merge to `main` or `develop`:

1. **Lint** — `ruff check nomarr/ tests/` run in a dedicated job. Zero-tolerance: any violation fails the gate.

2. **Backend tests** — `pytest tests/ -m "not container_only and not requires_database and not code_smell"`. Runs on every push and pull request.

3. **Frontend tests** — `npm run test -- --run` (Vitest in CI mode) run in a dedicated job. Gate replaces the current build-freshness timestamp check, which is retained as a separate informational step.

4. **CodeQL** — Static analysis scan scheduled weekly (every Monday at 06:00 UTC) against `main`, plus triggered on PRs to `main`. Uses the existing `.github/codeql/codeql-config.yml`. Languages: `python`, `javascript-typescript`.

Gate ordering: Lint and frontend tests run in parallel with backend tests. Build-and-push waits on all three test jobs (lint, backend, frontend) before proceeding.

## Consequences

**Positive:**

- PRs cannot merge with lint failures, broken backend tests, or failing frontend tests.
- CodeQL scans on a schedule catch regressions that a single post-merge scan would miss.
- Gates are explicit and documented — contributors know exactly what must pass.

**Negative:**

- CI wall time increases by ~2–3 min (frontend Vitest + lint jobs run in parallel with test, negligible on matrix).
- Scheduled CodeQL scans consume GitHub Actions minutes on a fixed cadence regardless of code churn.
- Lint gate requires ruff config to be stable; rule changes must be coordinated with a fix pass.

## References

ADR-017, ADR-018
