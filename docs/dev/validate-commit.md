# Validating CI Completion for an Exact Commit

Nomarr's CI is split into independent workflows (`.github/workflows/*.yml`, see
the [CI gates in CONTRIBUTING.md](../../CONTRIBUTING.md)). Before pushing a
branch — and before treating any commit as "done" — a contributor needs to know
that every required gate has finished **and** passed for that **exact** commit.

`scripts/validate_commit.py` is a local, read-only helper that answers that
question through the GitHub API. It is **validation only**: it never re-runs a
workflow, never re-queues a run, never merges, never pushes, never repairs a
failed check, and never mutates GitHub state.

## Prerequisites

* The [GitHub CLI](https://cli.github.com) (`gh`) is installed and on `PATH`.
* `gh` is authenticated: `gh auth status` should report a logged-in account with
  `repo` scope. The validator only issues read-only `gh api` GET calls (commit
  resolution and the check-runs query, plus a `gh repo view` to resolve the
  owner/repo when `--repo` is not given), so it needs read access to the
  repository — nothing more.

## Usage

```bash
python scripts/validate_commit.py <sha> [--trigger {push,pr,manual}] \
    [--repo owner/repo] [--require CHECK ...] [--skip CHECK ...]
```

`<sha>` is **required**: pass a full 40-character SHA or a sufficiently-unique
short SHA. A short SHA is resolved to its canonical full SHA through a read-only
`gh api repos/{owner}/{repo}/commits/{sha}` call before anything else; the
check-runs query, the exact-commit `head_sha` guard, and the report all use the
canonical SHA. There is deliberately no silent default — silently validating the
wrong commit is worse than asking for the SHA. Pass the current HEAD explicitly:

```bash
python scripts/validate_commit.py "$(git rev-parse HEAD)"
```

The validator queries the Checks API
(`GET /repos/{owner}/{repo}/commits/{sha}/check-runs`) and **rejects any result
whose `head_sha` differs from the requested (canonical) SHA** — the exact-commit
guarantee.

### Options

| Option | Meaning |
|--------|---------|
| `<sha>` | Commit SHA to validate (required): full 40-char or sufficiently-unique short SHA; a short SHA is resolved to the canonical full SHA first. |
| `--trigger` | Context selecting which checks are required. `push` (default), `pr`, or `manual`. |
| `--repo owner/repo` | Repository to query (default: derived from `gh repo view`). |
| `--require CHECK` | Require an extra check by job name regardless of trigger (repeatable), e.g. `--require analyze`. For the CodeQL matrix, `analyze` matches every real run named `Analyze (<language>)`. |
| `--skip CHECK` | Exclude a check by job name from the required set (repeatable). |

## Required-check contract

The contract is the single source of truth for what "all CI passed" means. It is
defined in `REQUIRED_CHECKS` inside `scripts/validate_commit.py`.

**Check names are GitHub check-run *job* names**, not workflow file names. The
Checks API reports each run's `name` as the workflow *job* (e.g. `lint`,
`build-and-push`), and each run carries its own `status`/`conclusion`/`head_sha`.
This job-level granularity is what makes exact-commit completion verifiable.
The sole exception is the CodeQL matrix: `analyze` matches real runs prefixed
`Analyze (` (see below).

| Job name | Workflow | Required on |
|----------|----------|-------------|
| `lint` | `backend-quality.yml` | push, pr, manual |
| `deptry` | `backend-quality.yml` | push, pr, manual |
| `test` | `backend-tests.yml` | push, pr, manual |
| `architecture-qc` | `backend-tests.yml` | push, pr, manual |
| `frontend-checks` | `frontend-checks.yml` | push, pr, manual |
| `build-and-push` | `docker-publish.yml` | push, manual |
| `promote` | `docker-publish.yml` | push, manual |
| `e2e` | `e2e.yml` | manual |
| `docs-check` | `docs-check.yml` | pr |
| `analyze` | `codeql.yml` | main-target only (matrix `Analyze (<lang>)` runs; see below) |

### Conditionality is explicit

A check is either **required** for the selected trigger, or reported as
**NOT-APPLICABLE** for it. A required check that is missing, pending, skipped,
cancelled, or failed is a **failure** (non-zero exit). A not-applicable check is
explicitly listed as N/A in the report — it is never silently counted as success
and never silently ignored.

* **`push`** (default): requires backend quality, backend tests, frontend
  checks, and Docker publish. `e2e` (manual-only), `docs-check` (PR-only), and
  `analyze` (main-target) are NOT-APPLICABLE.
* **`pr`**: requires backend quality, backend tests, frontend checks, and
  `docs-check`. Docker publish is NOT-APPLICABLE because `docker-publish.yml`
  has no `pull_request` trigger — no image is published on a PR, so a skipped
  publish is treated as not-applicable, never as success. `e2e` is
  NOT-APPLICABLE (manual-only).
* **`manual`**: requires every runnable gate, including `e2e`. `docs-check` is
  PR-only — `docs-check.yml` has no `workflow_dispatch` trigger — so it is
  NOT-APPLICABLE on a manual run unless explicitly required.

### CodeQL (`analyze`) is main-target only and opt-in

`codeql.yml` runs on pushes to `main`, pull requests to `main`, and a weekly
schedule. It does **not** run on `develop`/`feat/*`. Because a bare SHA cannot
reveal the target branch, `analyze` is not required by default. When validating
a main-target commit, require it explicitly:

```bash
python scripts/validate_commit.py <sha> --trigger pr --require analyze
```

`analyze` is the one exception to the exact job-name contract, and the reason
is the CodeQL matrix. The `codeql.yml` `analyze` job declares
`name: Analyze (${{ matrix.language }})` (languages: `actions`, `go`,
`javascript-typescript`, `python`), so GitHub names the *real* check runs
`Analyze (actions)`, `Analyze (go)`, `Analyze (javascript-typescript)`,
`Analyze (python)` — never a bare `analyze`. The validator therefore uses a
**prefix-aware matcher** for this entry: it consumes and requires every check
run whose name starts with `Analyze (`. When required, all matching matrix legs
must complete with a `success` conclusion — a missing, pending, or
unsuccessful leg (including an incomplete matrix that silently drops a language)
is a validation failure. The public flag remains `--require analyze`; the
prefix matcher is simply how that key reconciles real GitHub check-run names.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Every required check is present, completed, and successful; no run belongs to a different SHA. |
| `1` | Validation failed: a required check is missing, pending/in-progress, or completed with a non-success conclusion (`failure`/`skipped`/`cancelled`/`neutral`/`timed_out`/`action_required`/`stale`), or a returned run's `head_sha` does not match the requested SHA. Diagnostics name each offending check and why. |
| `2` | Could not validate: `gh` missing/unauthenticated, network/auth failure, malformed API response, or invalid arguments. |

Only `success` counts as a passing conclusion for a required gate; every other
terminal conclusion is a failure.

## Scope limits

* **Validation only.** The script never reruns a workflow, re-queues a run,
  merges, pushes, or creates/deletes anything on GitHub. It never repairs a
  failed check.
* **No self-hosted runner.** It expects the existing CI infrastructure (the
  split workflows) and does not provision or alter a runner.
* A non-zero exit means "do not consider this commit done" — it does not make
  the underlying check pass.

## Example output

```text
Validating commit 4cda413a1bab82986a20a0296ba3bf75303d88ba (trigger: push)

Required checks:
  [N/A  ] analyze            CodeQL security gate (job 'analyze'); main-target only — use --require analyze
        (CodeQL security gate (job 'analyze'); main-target only — use --require analyze)
  [PASS ] architecture-qc    completed + success
  [PASS ] build-and-push     completed + success
  [PASS ] deptry             completed + success
  [N/A  ] docs-check         PR-only; NOT-APPLICABLE on push/manual
        (PR-only; NOT-APPLICABLE on push/manual)
  [N/A  ] e2e                manual-only (workflow_dispatch); NOT-APPLICABLE on push/pr
        (manual-only (workflow_dispatch); NOT-APPLICABLE on push/pr)
  [PASS ] frontend-checks    completed + success
  [PASS ] lint               completed + success
  [PASS ] promote            completed + success
  [MISS ] test               required check 'test' has no matching run for 4cda413 (4cda413a1bab82986a20a0296ba3bf75303d88ba)

FAILURE: not all required checks succeeded.
```
