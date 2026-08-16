---
name: ci-validate-commit
description: The CI exact-commit validator (scripts/validate_commit.py) contract — REQUIRED_CHECKS job-name semantics, the CodeQL "Analyze (" check-run prefix mismatch, Phase 3 amendment constraints, and matching machinery. Use when editing the validator, its tests (tests/unit/scripts/test_validate_commit.py), the required-check contract, or CI check-run naming in .github/workflows/codeql.yml.
---

# CI Exact-Commit Validator (validate_commit.py)

## Mental Model

`scripts/validate_commit.py` proves every required CI gate completed AND passed
for one exact commit SHA, using read-only `gh api GET` calls. The contract is
`REQUIRED_CHECKS` inside the script — a dict of `CheckSpec(name, workflow,
triggers, note)` keyed by GitHub check-run **job name** (not workflow file
name). Matching is exact: `by_name.get(name, [])` (line ~386). Each returned
run's `head_sha` must equal the requested SHA (exact-commit guard). Exit codes:
0 = all required passed, 1 = missing/pending/failed/wrong-commit, 2 = env error.

## Coverage

**Documented:** contract structure, CodeQL `analyze` prefix-matcher amendment
(Phase 3 of TASK-workflow-cleanup-A-phases-1-2), matching machinery, prior QA
notes.
**Not yet documented:** none known.
**Last extended:** 2026-08-16

## Key Findings

### The `analyze` exact-match is impossible (guaranteed false MISSING)
- **Location:** `scripts/validate_commit.py:221-226` (contract entry),
  `scripts/validate_commit.py:386` (exact lookup),
  `.github/workflows/codeql.yml:24` (`name: Analyze (${{ matrix.language }})`),
  `.github/workflows/codeql.yml:44-53` (matrix: actions, go,
  javascript-typescript, python)
- **What:** Contract expects a check-run named exactly `analyze`, but CodeQL
  produces `Analyze (actions)`, `Analyze (go)`, `Analyze (javascript-typescript)`,
  `Analyze (python)`. `--require analyze` therefore always reports MISSING on a
  real CodeQL run. Fail-closed but wrong.
- **Why it matters:** Any amendment must change how `analyze` resolves.

### Phase 3 amendment already chose the prefix-based matcher
- **Location:** `artifacts/plans/pending/TASK-workflow-cleanup-A-phases-1-2.md:59-65`
- **What:** Unchecked Phase 3 steps: replace the impossible exact match with a
  documented prefix matcher for check-run names beginning with `Analyze (`;
  keep contract key `analyze` and `--require analyze` stable; do NOT modify
  `.github/workflows/codeql.yml`; update docstring/--help, CONTRIBUTING.md and
  docs/dev/validate-commit.md; extend tests with mocked `Analyze (python)` /
  `Analyze (javascript-typescript)` runs; re-run Phase 2 verification subset.
- **Why it matters:** The prefix-vs-exact-matrix question is already decided in
  the plan. Rationale in the plan: prefix follows future matrix language
  additions without validator edits, and matches only the CodeQL display-name
  namespace instead of accepting an unrelated exact `analyze` run.

### Matrix all-must-pass machinery already exists
- **Location:** `scripts/validate_commit.py:398-422` (multiple same-name runs
  all must pass), `scripts/validate_commit.py:424-427` (unmatched runs are
  informational `extra_runs`, never failures)
- **What:** The validator already requires every run of a given name to pass.
  A prefix matcher generalizes this: every run matching the prefix must pass.
  Exact matrix entries would be fail-open on matrix additions — a new
  language's run would land in `extra_runs` (informational) and silently skip
  validation.
- **Why it matters:** Any matrix-language change to codeql.yml stays covered
  without touching the validator under the prefix approach.

### Docs drift: ADR-019 languages vs actual matrix
- **Location:** `artifacts/decisions/ADR-019-...codeql.md` (languages `python`,
  `javascript-typescript`; weekly Monday 06:00 UTC), actual
  `.github/workflows/codeql.yml:19-20,44-53` (4 languages; cron `40 5 * * 3`)
- **What:** ADR-019's CodeQL languages/schedule no longer match the workflow.
- **Why it matters:** Evidence that the matrix changes independently of
  documentation — supports the lockstep-free prefix representation.

## Critical Invariants

- Check-name contract = GitHub check-run JOB names, never workflow file names.
- Validator is read-only: only `gh api GET` + `gh repo view`; never mutates
  GitHub state, never reruns/repairs/merges.
- Exact-commit guard: every returned run's `head_sha` must match the requested
  SHA, or validation fails (exit 1).
- NOT-APPLICABLE is explicit, never silent success or silent ignore.
- `--require analyze` must keep working as the main-target CodeQL opt-in (bare
  SHA cannot reveal target branch).
- CodeQL is NOT required by default for push/pr triggers.

## Sources

- `scripts/validate_commit.py`, `tests/unit/scripts/test_validate_commit.py`
- `docs/dev/validate-commit.md`, `CONTRIBUTING.md` (lines ~196-234)
- `.github/workflows/codeql.yml`, `.github/codeql/codeql-config.yml`
- `artifacts/plans/pending/TASK-workflow-cleanup-A-phases-1-2.md` (Phase 3)
- `artifacts/decisions/ADR-019`
- Logs: qa-test-analyzer L226 (matrix all-must-pass path untested), exec-worker
  L275 (real gh query confirms fail-closed), support-librarian L60/L61
