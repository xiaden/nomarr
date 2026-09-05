---
name: ci-validate-commit
description: The CI exact-commit validator (scripts/validate_commit.py) contract — REQUIRED_CHECKS job-name semantics, the CodeQL "Analyze (" prefix matcher, matching machinery, and prior QA notes. Use when editing the validator, its tests (tests/unit/scripts/test_validate_commit.py), the required-check contract, or CI check-run naming in .github/workflows/codeql.yml.
---

# CI Exact-Commit Validator (validate_commit.py)

## Mental Model

`scripts/validate_commit.py` proves every required CI gate completed AND passed
for one exact commit SHA, using read-only `gh api GET` calls. The contract is
`REQUIRED_CHECKS` inside the script — a dict of `CheckSpec(name, workflow,
triggers, note, prefix_match, expected_names)` keyed by GitHub check-run **job
name** (not workflow file name). Matching is exact for ordinary entries
(`run_name == spec.name`) with **one exception**: the CodeQL `analyze` entry
declares `prefix_match="Analyze ("`, so any check run whose name starts with
that prefix is consumed (see Key Findings). `CheckSpec._run_matches_spec`
(`scripts/validate_commit.py:387-397`) implements both modes. Each returned
run's `head_sha` must equal the requested SHA (exact-commit guard). Exit codes:
0 = all required passed, 1 = missing/pending/failed/wrong-commit, 2 = env error.

## Coverage

**Documented:** contract structure, the CodeQL `Analyze (` prefix-matcher as the
CURRENT implemented matching contract, the fail-closed `expected_names` matrix
machinery, matching machinery, prior QA notes, docs drift.
**Not yet documented:** none known.
**Last extended:** 2026-09-04 (reconciled to the live validator)

## Key Findings

### The `analyze` prefix matcher is IMPLEMENTED (not merely planned)
- **Location:** `scripts/validate_commit.py:259-273` (`analyze` CheckSpec),
  `scripts/validate_commit.py:387-397` (`_run_matches_spec` startswith),
  `scripts/validate_commit.py:106-116` (module docstring),
  `.github/workflows/codeql.yml:24` (`name: Analyze (${{ matrix.language }})`),
  `.github/workflows/codeql.yml:44-53` (matrix: actions, go,
  javascript-typescript, python)
- **What:** The `analyze` contract entry has `prefix_match="Analyze ("` plus
  `expected_names=frozenset({"Analyze (actions)", "Analyze (go)",
  "Analyze (javascript-typescript)", "Analyze (python)"})`. CodeQL produces
  those real suffixed check-run names (never bare `analyze`), and the matcher
  consumes every run whose name starts with `Analyze (`. The public key/flag
  stays `analyze` (`--require analyze`); `CheckSpec.prefix_match` and
  `expected_names` are the implementation detail. This supersedes the earlier
  exact-match-`analyze` behavior (which would have reported a guaranteed false
  MISSING against real CodeQL runs) — do not reintroduce an exact match here.
- **Why it matters:** Any edit must keep the prefix matcher and its
  `expected_names` set in sync with `codeql.yml`'s actual matrix languages.

### Matrix legs fail closed via `expected_names`
- **Location:** `scripts/validate_commit.py:482-494`
- **What:** When a spec has `expected_names` (the CodeQL matrix), every known
  leg must be present among the consumed runs. A matrix that silently drops a
  language is a `FAIL` naming the missing leg(s) — not a silent pass. Partial
  matrices never count as success.
- **Why it matters:** A matrix-language change to `codeql.yml` must be mirrored
  in `expected_names` (and the tests) or validation fails closed rather than
  silently skipping a language.

### All matching runs of a name must pass; bare `analyze` does not satisfy
- **Location:** `scripts/validate_commit.py:496-521` (multiple same-name runs
  all must pass), `scripts/validate_commit.py:527-532` (unmatched runs are
  informational `extra_runs`, never failures)
- **What:** Every run consumed by a contract entry must be `completed` with a
  `success` conclusion. A check named exactly `analyze` (the bare job id) does
  NOT satisfy the matrix — only `Analyze (`-prefixed runs are consumed
  (`test_bare_analyze_run_does_not_satisfy_matrix` in the test file). Matrix
  legs are consumed by the `analyze` entry, so they are never reported as
  `extra_runs`.
- **Why it matters:** The all-must-pass machinery plus `expected_names` keep
  matrix additions/deletions covered without silently widening or narrowing the
  gate.

### Docs drift: ADR-019 languages/schedule vs actual codeql.yml
- **Location:** `artifacts/decisions/ADR-019-...codeql.md` (languages `python`,
  `javascript-typescript`; weekly Monday 06:00 UTC), actual
  `.github/workflows/codeql.yml:20,44-53` (cron `40 5 * * 3`; 4 languages:
  actions, go, javascript-typescript, python)
- **What:** ADR-019's recorded CodeQL languages and weekly schedule no longer
  match the workflow (which now runs 4 languages on Wednesdays).
- **Why it matters:** Evidence that the matrix changes independently of
  documentation — the validator must derive the expected legs from the live
  `codeql.yml`, not from ADR-019.

## Critical Invariants

- Check-name contract = GitHub check-run JOB names, never workflow file names;
  the sole exception is the `analyze` prefix matcher on the CodeQL matrix.
- Validator is read-only: only `gh api GET` + `gh repo view`; never mutates
  GitHub state, never reruns/repairs/merges.
- Exact-commit guard: every returned run's `head_sha` must match the requested
  (canonical) SHA, or validation fails (exit 1). Short SHAs are resolved to the
  canonical full SHA via a read-only commits GET before the check-runs query.
- NOT-APPLICABLE is explicit, never silent success or silent ignore.
- `--require analyze` must keep working as the main-target CodeQL opt-in (bare
  SHA cannot reveal target branch).
- CodeQL is NOT required by default for push/pr triggers (`analyze.triggers` is
  empty; it only becomes required via `--require analyze`).
- Fail-closed matrix: dropping a `codeql.yml` language leg is a FAIL, never a
  silent pass.

## Sources

- `scripts/validate_commit.py`, `tests/unit/scripts/test_validate_commit.py`
  (esp. `TestCodeQlMatrixMatching`)
- `docs/dev/validate-commit.md` (up to date with the prefix matcher),
  `CONTRIBUTING.md` (CI gates section)
- `.github/workflows/codeql.yml`, `.github/codeql/codeql-config.yml`
- `artifacts/decisions/ADR-019` (historical; records the older 2-language /
  Monday-06:00 schedule that no longer matches codeql.yml)
- Logs: qa-test-analyzer L226, exec-worker L275, support-librarian L60/L61
