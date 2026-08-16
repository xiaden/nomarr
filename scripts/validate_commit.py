#!/usr/bin/env python3
"""Validate that all required CI checks completed successfully for one exact commit.

`validate_commit.py` is a **local-only, read-only** helper that answers a single
question: *did every required CI gate succeed for exactly this commit SHA?* It
never reruns, repairs, merges, pushes, or otherwise mutates GitHub state. It
queries the GitHub REST API exclusively through read-only ``gh api`` GET calls
(commit resolution and check-runs, plus one ``gh repo view`` to resolve the
owner/repo) and exits non-zero whenever
anything required is missing, pending, or unsuccessful, or when the response
does not correspond to the requested SHA.

Why this exists
---------------
Nomarr's CI is split into independent workflows (see ``.github/workflows/*.yml``
and the phase-1 cleanup). A contributor pushing to a branch needs a local command
that proves, for the *exact* commit being pushed, that every required gate has
finished and passed. This script provides that proof. Because each returned check
run carries its own ``head_sha``, the script can (and does) reject results that
belong to a different commit — the "exact-commit completion" guarantee.

Usage
-----
::

    python scripts/validate_commit.py <sha> [--trigger {push,pr,manual}] \\
        [--repo owner/repo] [--require NAME ...] [--skip NAME ...]

``<sha>`` is **required** (a full 40-char SHA or a sufficiently-unique short SHA).
A short SHA is resolved to its canonical full 40-char SHA through a read-only
``gh api repos/{owner}/{repo}/commits/{sha}`` GET *before* the check-runs query,
and the canonical SHA is used for the ``head_sha`` exact-commit guard and all
reporting. There is deliberately no silent default: validating the wrong commit
silently is worse than asking for the SHA. Use ``$(git rev-parse HEAD)`` to pass
the current HEAD explicitly::

    python scripts/validate_commit.py "$(git rev-parse HEAD)"

Exit codes
----------
* ``0``  — every required check is present, completed, and successful, and no
  returned run belongs to a different SHA.
* ``1``  — validation failed: a required check is missing, pending/in-progress,
  or completed with a non-success conclusion (failure/skipped/cancelled/
  neutral/timed_out/action_required/stale), or a returned run's ``head_sha`` does
  not match the requested SHA. Diagnostics name each offending check and why.
* ``2``  — could not validate: ``gh`` is not installed or not authenticated,
  the network/auth call failed, the API response was malformed, or arguments are
  invalid. This is an environment/tooling failure, not a check result.

Required-check contract
-----------------------
The contract is the single source of truth for what "all CI passed" means and is
defined in :data:`REQUIRED_CHECKS` below (and in the companion docs
``docs/dev/validate-commit.md`` and the ``CONTRIBUTING.md`` section).

**Check-name contract: job names from the Checks API.** The script keys the
contract on the GitHub check-run *job name* (``check_runs[].name`` returned by
``GET /repos/{owner}/{repo}/commits/{sha}/check-runs``), not the workflow file
name. GitHub names those check runs after the workflow *job* (e.g. ``lint``,
``test``, ``build-and-push``), not after the workflow file (e.g. ``Backend
Quality``). Job names are the granular unit whose ``status``/``conclusion``
reflect real completion, and each carries its own ``head_sha``, which makes the
exact-commit guarantee verifiable per run. The job-name→workflow mapping:

* ``.github/workflows/backend-quality.yml``  → jobs ``lint``, ``deptry``
* ``.github/workflows/backend-tests.yml``    → jobs ``test``, ``architecture-qc``
* ``.github/workflows/frontend-checks.yml``  → job  ``frontend-checks``
* ``.github/workflows/docker-publish.yml``   → jobs ``build-and-push``, ``promote``
* ``.github/workflows/e2e.yml``              → job  ``e2e``
* ``.github/workflows/docs-check.yml``       → job  ``docs-check``
* ``.github/workflows/codeql.yml``           → job  ``analyze`` (see below)

**Conditionality is explicit.** Several gates are not required on every commit.
Each contract entry lists the ``--trigger`` contexts in which it is *required*.
A required-but-absent/skipped/unsuccessful check is a **failure**. A check that
is documented not to apply to the selected trigger is reported as
**NOT-APPLICABLE** (never counted as success, never silently ignored — it is
explicitly listed in the report). Current applicability:

* ``push`` (default) — the commit was pushed to ``main``/``develop``/``feat/*``.
  Required: backend quality (``lint``, ``deptry``), backend tests (``test``,
  ``architecture-qc``), frontend checks (``frontend-checks``), and Docker publish
  (``build-and-push``, ``promote``). ``e2e`` (manual-only), ``docs-check``
  (PR-only), and ``analyze`` (CodeQL, main-target only) are NOT-APPLICABLE.
* ``pr`` — the commit is a PR head. Required: backend quality, backend tests,
  frontend checks, and ``docs-check``. ``build-and-push``/``promote`` are
  NOT-APPLICABLE (docker-publish.yml has no PR trigger, so no image is published
  on a PR — the earlier open question is resolved here by documenting it as
  not-applicable rather than treating a skipped publish as success). ``e2e`` is
  NOT-APPLICABLE (manual-only). ``analyze`` is NOT-APPLICABLE for develop-target
  PRs.
* ``manual`` — requires every gate that can run, including ``e2e``.
  ``docs-check`` is PR-only (``docs-check.yml`` has no ``workflow_dispatch``
  trigger), so it is NOT-APPLICABLE unless explicitly required with
  ``--require docs-check``.

**CodeQL (``analyze``) is main-target only and opt-in.** ``codeql.yml`` runs on
pushes to ``main``, PRs to ``main``, and a weekly schedule — it does not run on
``develop``/``feat/*``. A bare SHA cannot tell us the target branch, so CodeQL
is NOT required by default for ``push``/``pr``. When validating a main-target
commit, require it explicitly::

    python scripts/validate_commit.py <sha> --trigger pr --require analyze

The ``analyze`` contract is the single exception to the exact job-name rule,
and the reason is the CodeQL matrix. The ``codeql.yml`` ``analyze`` job declares
``name: Analyze (${{ matrix.language }})`` (languages: ``actions``, ``go``,
``javascript-typescript``, ``python``), so GitHub names the real check runs
``Analyze (actions)``, ``Analyze (go)``, and so on — never bare ``analyze``.
The contract therefore uses a **prefix-aware matcher**: it consumes and requires
every check run whose name starts with ``Analyze (`` (``CheckSpec.prefix_match``).
When required, every matching matrix leg must complete with a ``success``
conclusion — a missing, pending, or unsuccessful leg is a validation failure.
The public key/flag stays ``analyze`` (``--require analyze``); the matcher is an
implementation detail of how that key reconciles real GitHub run names.

Scope limits
------------
* Validation only. This script never re-runs a workflow, never re-queues a run,
  never merges, never pushes, never repairs a failed check, and never creates or
  deletes anything on GitHub.
* It expects a pre-existing CI infrastructure (the split workflows) — it does not
  provision or alter a runner, and there is no self-hosted-runner automation.
* A non-zero exit means "do not consider this commit done" — it does not make the
  underlying check pass.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

# Exit codes (documented in the module docstring and the docs).
EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_ENV_ERROR = 2

# Conclusions that GitHub reports for a completed check run. Only ``success`` is
# a passing result for a required gate; every other terminal conclusion
# (failure, skipped, cancelled, neutral, timed_out, action_required, stale) is
# treated as a failure. ``null`` conclusion with ``status == in_progress`` /
# ``queued`` means the check has not finished and is reported as pending.
SUCCESS_CONCLUSIONS = frozenset({"success"})
PENDING_STATUSES = frozenset({"queued", "in_progress"})

DEFAULT_TRIGGER = "push"
VALID_TRIGGERS = ("push", "pr", "manual")


@dataclass(frozen=True)
class CheckSpec:
    """Contract entry for one required check.

    Attributes:
        name: public contract key and report label. Also the exact check-run
            job name matched from the Checks API (``check_runs[].name``) when
            ``prefix_match`` is unset.
        workflow: workflow file the job belongs to (for grouping/reporting).
        triggers: ``--trigger`` contexts in which this check is REQUIRED.
        note: conditionality / rationale shown in the report and --help.
        prefix_match: optional prefix matched against the check-run name for
            jobs whose real checks are suffixed (matrix jobs in particular).
            When set, a check run is consumed by this entry if its name starts
            with ``prefix_match`` (see ``analyze`` below).
        expected_names: when ``prefix_match`` is set, the exact run names that
            MUST be present for the check to pass (the known matrix legs). This
            fails closed when a matrix silently drops a leg — a partial matrix
            is not treated as success.
    """

    name: str
    workflow: str
    triggers: frozenset[str]
    note: str = ""
    prefix_match: str | None = None
    expected_names: frozenset[str] = frozenset()


# ---------------------------------------------------------------------------
# Required-check contract — single source of truth (see module docstring).
# ---------------------------------------------------------------------------
REQUIRED_CHECKS: dict[str, CheckSpec] = {
    # Backend quality (.github/workflows/backend-quality.yml) — push + PR.
    "lint": CheckSpec(
        name="lint",
        workflow="backend-quality.yml",
        triggers=frozenset({"push", "pr", "manual"}),
        note="ruff check + ruff format --check + mypy + lint-imports",
    ),
    "deptry": CheckSpec(
        name="deptry",
        workflow="backend-quality.yml",
        triggers=frozenset({"push", "pr", "manual"}),
        note="dependency audit",
    ),
    # Backend tests (.github/workflows/backend-tests.yml) — push + PR.
    "test": CheckSpec(
        name="test",
        workflow="backend-tests.yml",
        triggers=frozenset({"push", "pr", "manual"}),
        note="pytest unit/integration gate",
    ),
    "architecture-qc": CheckSpec(
        name="architecture-qc",
        workflow="backend-tests.yml",
        triggers=frozenset({"push", "pr", "manual"}),
        note="ADR-042 architecture/quality enforcement (tests/test_architecture_qc.py)",
    ),
    # Frontend checks (.github/workflows/frontend-checks.yml) — push + PR.
    "frontend-checks": CheckSpec(
        name="frontend-checks",
        workflow="frontend-checks.yml",
        triggers=frozenset({"push", "pr", "manual"}),
        note="npm ci + lint + tsc + vitest + production build",
    ),
    # Docker publish (.github/workflows/docker-publish.yml) — push/manual only,
    # never PR (no image is published on a pull request).
    "build-and-push": CheckSpec(
        name="build-and-push",
        workflow="docker-publish.yml",
        triggers=frozenset({"push", "manual"}),
        note="docker build/push; NOT-APPLICABLE on PRs (no PR trigger)",
    ),
    "promote": CheckSpec(
        name="promote",
        workflow="docker-publish.yml",
        triggers=frozenset({"push", "manual"}),
        note="image promote/re-tag; NOT-APPLICABLE on PRs (no PR trigger)",
    ),
    # E2E (.github/workflows/e2e.yml) — manual-only.
    "e2e": CheckSpec(
        name="e2e",
        workflow="e2e.yml",
        triggers=frozenset({"manual"}),
        note="manual-only (workflow_dispatch); NOT-APPLICABLE on push/pr",
    ),
    # Docs consistency (.github/workflows/docs-check.yml) — PR only
    # (docs-check.yml has no workflow_dispatch trigger, so a manual run must
    # not falsely require it).
    "docs-check": CheckSpec(
        name="docs-check",
        workflow="docs-check.yml",
        triggers=frozenset({"pr"}),
        note="PR-only; NOT-APPLICABLE on push/manual",
    ),
    # CodeQL Advanced (.github/workflows/codeql.yml) — main-target push/PR +
    # weekly schedule. Not required by default because a bare SHA cannot reveal
    # the target branch; require explicitly with --require analyze.
    # The codeql.yml `analyze` job is a matrix with `name: Analyze (${{ matrix.language }})`,
    # so the real GitHub check-run names are suffixed per language — `Analyze (actions)`,
    # `Analyze (go)`, `Analyze (python)`, etc. — not bare `analyze`. Use
    # prefix_match to accept / require every language leg of that matrix; when
    # required, ALL of them must complete successfully.
    "analyze": CheckSpec(
        name="analyze",
        workflow="codeql.yml",
        triggers=frozenset(),
        prefix_match="Analyze (",
        expected_names=frozenset(
            {
                "Analyze (actions)",
                "Analyze (go)",
                "Analyze (javascript-typescript)",
                "Analyze (python)",
            }
        ),
        note=("CodeQL security gate (job 'analyze'); main-target only — use --require analyze"),
    ),
}


class GhNotInstalledError(RuntimeError):
    """Raised when the ``gh`` CLI is not on PATH."""


class GhInvocationError(RuntimeError):
    """Raised when a ``gh`` call fails (missing auth, network, non-zero exit)."""


class MalformedResponseError(RuntimeError):
    """Raised when ``gh`` returns output that is not the expected JSON shape."""


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``gh`` and return the completed process.

    Raises:
        GhNotInstalledError: ``gh`` is not on PATH.
        GhInvocationError: ``gh`` returned a non-zero exit code.
    """
    if shutil.which("gh") is None:
        raise GhNotInstalledError(
            "The `gh` CLI is required but was not found on PATH. "
            "Install GitHub CLI (https://cli.github.com) and run `gh auth login`."
        )
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - env-dependent
        raise GhInvocationError(f"`gh` timed out after 60s: {' '.join(args)}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise GhInvocationError(f"`gh {' '.join(args)}` failed (exit {proc.returncode}): {detail}")
    return proc


def resolve_repo(repo: str | None) -> str:
    """Return the ``owner/repo`` to query.

    If ``--repo`` was supplied it is returned unchanged; otherwise it is derived
    from a read-only ``gh repo view`` (the repo GitHub CLI is currently pointing
    at, usually inferred from the git remote).
    """
    if repo:
        return repo
    proc = _run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    try:
        value = proc.stdout.strip()
    except AttributeError:  # pragma: no cover - defensive
        raise MalformedResponseError("`gh repo view` returned no output") from None
    if not value:
        raise MalformedResponseError("`gh repo view` returned an empty owner/repo")
    return value


def resolve_commit_sha(repo: str, sha: str) -> str:
    """Resolve a (possibly short) SHA to its canonical full 40-char SHA.

    Uses a read-only ``gh api repos/{repo}/commits/{sha}`` GET and returns the
    commit's canonical ``sha`` so the check-runs query, the ``head_sha``
    exact-commit guard, and the report all use one canonical SHA.

    Raises:
        MalformedResponseError: the response is not JSON or lacks a canonical
            ``sha`` field.
    """
    endpoint = f"repos/{repo}/commits/{sha}"
    proc = _run_gh(["api", endpoint])
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MalformedResponseError(f"`gh api {endpoint}` returned non-JSON output: {proc.stdout[:200]!r}") from exc
    canonical = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(canonical, str) or len(canonical) != 40:
        raise MalformedResponseError(f"`gh api {endpoint}` response missing canonical `sha`: {str(payload)[:200]!r}")
    return canonical


def fetch_check_runs(repo: str, sha: str) -> list[dict]:
    """Fetch the check runs for ``sha`` via a read-only ``gh api`` GET.

    Returns the raw ``check_runs[]`` list. Raises ``MalformedResponseError`` if
    the response is not the expected shape (missing ``check_runs`` or
    ``total_count``).
    """
    endpoint = f"repos/{repo}/commits/{sha}/check-runs"
    proc = _run_gh(["api", endpoint])
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise MalformedResponseError(f"`gh api {endpoint}` returned non-JSON output: {proc.stdout[:200]!r}") from exc
    if not isinstance(payload, dict) or "check_runs" not in payload:
        raise MalformedResponseError(f"`gh api {endpoint}` response missing `check_runs`: {str(payload)[:200]!r}")
    runs = payload["check_runs"]
    if not isinstance(runs, list):
        raise MalformedResponseError(f"`gh api {endpoint}` `check_runs` is not a list: {str(runs)[:200]!r}")
    return runs


def _run_status(run: dict) -> tuple[str, str | None]:
    """Return ``(status, conclusion)`` for a check run, tolerant of shape."""
    status = run.get("status") or "unknown"
    conclusion = run.get("conclusion")
    return status, conclusion


def _run_matches_spec(run_name: str, spec: CheckSpec) -> bool:
    """Whether a check-run ``name`` is consumed by ``spec``.

    Exact job-name contract by default (``run_name == spec.name``). When the
    spec declares ``prefix_match`` (the CodeQL ``analyze`` matrix), any run whose
    name starts with that prefix is consumed — this keys on the *real* GitHub
    check-run names like ``Analyze (python)`` instead of the bare job id.
    """
    if spec.prefix_match:
        return run_name.startswith(spec.prefix_match)
    return run_name == spec.name


@dataclass
class CheckResult:
    """Outcome of validating one contract check against the fetched runs."""

    name: str
    spec: CheckSpec
    state: str  # PASS | FAIL | MISSING | NOT-APPLICABLE
    detail: str = ""


@dataclass
class Report:
    """Aggregated validation outcome."""

    results: list[CheckResult] = field(default_factory=list)
    extra_runs: list[dict] = field(default_factory=list)
    wrong_commit_runs: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.results or all(r.state == "PASS" or r.state == "NOT-APPLICABLE" for r in self.results)


def validate_checks(
    sha: str,
    runs: list[dict],
    trigger: str,
    require: set[str] | None = None,
    skip: set[str] | None = None,
) -> Report:
    """Validate the fetched check runs against the required-check contract.

    Args:
        sha: the exact commit SHA being validated.
        runs: raw check-run list from the Checks API.
        trigger: the ``--trigger`` context selecting required checks.
        require: extra check names to require regardless of trigger.
        skip: check names to exclude from the required set.

    Returns a :class:`Report` describing each contract check plus any runs that
    could not be reconciled (wrong ``head_sha`` or not in the contract).
    """
    require = require or set()
    skip = skip or set()

    by_name: dict[str, list[dict]] = {}
    report = Report()
    for run in runs:
        name = str(run.get("name") or "")
        by_name.setdefault(name, []).append(run)

    # Exact-commit guard: every returned run must belong to the requested SHA.
    # A run with a falsy/missing head_sha is outside the contract — fail closed.
    for run in runs:
        head = run.get("head_sha")
        if not head or head != sha:
            report.wrong_commit_runs.append(run)

    # Evaluate each contract check.
    for name, spec in REQUIRED_CHECKS.items():
        applicable = trigger in spec.triggers or name in require
        if name in skip or not applicable:
            state = "NOT-APPLICABLE"
            note = spec.note or f"not required for trigger '{trigger}'"
            report.results.append(CheckResult(name, spec, state, note))
            continue

        matches = [run for run in runs if _run_matches_spec(str(run.get("name") or ""), spec)]
        if not matches:
            report.results.append(
                CheckResult(
                    name,
                    spec,
                    "MISSING",
                    f"required check '{spec.name}' has no matching run for {sha[:7]} ({sha})",
                )
            )
            continue

        # For a matrix (prefix_match + expected_names), every known leg must be
        # present. A matrix that silently drops a language is a FAIL, not a
        # pass — name the missing leg(s).
        if spec.expected_names:
            present = {str(run.get("name") or "") for run in matches}
            missing_legs = sorted(spec.expected_names - present)
            if missing_legs:
                report.results.append(
                    CheckResult(
                        name,
                        spec,
                        "FAIL",
                        "missing expected matrix leg(s): " + ", ".join(missing_legs),
                    )
                )
                continue

        # Multiple runs with the same name (e.g. a matrix) all must pass.
        failed = False
        details: list[str] = []
        for run in matches:
            leg = str(run.get("name") or spec.name)
            head = run.get("head_sha")
            if not head or head != sha:
                failed = True
                details.append(f"{leg}: head_sha={head!r} != requested {sha[:7]} (wrong commit)")
                continue
            status, conclusion = _run_status(run)
            if status in PENDING_STATUSES:
                failed = True
                details.append(f"{leg}: pending ({status})")
            elif status != "completed":
                failed = True
                details.append(f"{leg}: unfinished (status={status})")
            elif conclusion not in SUCCESS_CONCLUSIONS:
                failed = True
                details.append(f"{leg}: conclusion={conclusion!r} (not success)")
            else:
                details.append("ok")
        if failed:
            report.results.append(CheckResult(name, spec, "FAIL", "; ".join(details) or "unsuccessful"))
        else:
            report.results.append(CheckResult(name, spec, "PASS", "completed + success"))

    # Runs that appear in the API but match no contract entry are reported as
    # informational (e.g. old monolith jobs, third-party apps) — never failures.
    # A run is consumed either by an exact contract key or by a prefix matcher
    # (e.g. every `Analyze (...)` leg is consumed by the analyze entry).
    consumed_names = set()
    for name in by_name:
        if any(_run_matches_spec(name, spec) for spec in REQUIRED_CHECKS.values()):
            consumed_names.add(name)
    for name in sorted(set(by_name) - consumed_names):
        report.extra_runs.extend(by_name[name])

    return report


def _format_report(report: Report, sha: str, trigger: str) -> str:
    """Render a human-readable report to a string."""
    lines: list[str] = []
    lines.append(f"Validating commit {sha} (trigger: {trigger})")
    lines.append("")

    if report.wrong_commit_runs:
        lines.append("EXACT-COMMIT VIOLATION: the API returned runs for a different SHA:")
        lines.extend(
            f"  - {run.get('name')}: head_sha={run.get('head_sha')} (requested {sha})"
            for run in report.wrong_commit_runs
        )

    lines.append("Required checks:")
    for r in sorted(report.results, key=lambda r: r.name):
        marker = {
            "PASS": "PASS ",
            "FAIL": "FAIL ",
            "MISSING": "MISS ",
            "NOT-APPLICABLE": "N/A  ",
        }[r.state]
        detail = r.detail or ""
        lines.append(f"  [{marker}] {r.name:<18} {detail}")
        if r.state == "NOT-APPLICABLE" and r.spec.note:
            lines.append(f"        ({r.spec.note})")

    if report.extra_runs:
        lines.append("")
        lines.append("Extra check runs not in the contract (informational only):")
        for run in report.extra_runs:
            status, conclusion = _run_status(run)
            lines.append(f"  - {run.get('name')}: status={status} conclusion={conclusion}")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_commit.py",
        description=(
            "Verify all required CI checks completed successfully for one exact "
            "commit SHA, using read-only `gh api` queries. Validation only — "
            "never reruns, repairs, merges, or mutates GitHub state."
        ),
        epilog=(
            "Required-check contract (check-run names from the Checks API): "
            + ", ".join(sorted(REQUIRED_CHECKS))
            + ". 'analyze' is the CodeQL gate (codeql.yml analyze matrix, real "
            "runs named 'Analyze (<language>)'); main-target only — require it "
            "explicitly with --require analyze. "
            "See docs/dev/validate-commit.md for full semantics."
        ),
    )
    parser.add_argument(
        "sha",
        help=(
            "Exact commit SHA to validate (required; full 40-char or "
            "sufficiently-unique short SHA — a short SHA is resolved to the "
            "canonical full SHA via a read-only `gh api` commit lookup before "
            "validation; use $(git rev-parse HEAD) for the current HEAD)."
        ),
    )
    parser.add_argument(
        "--trigger",
        choices=list(VALID_TRIGGERS),
        default=DEFAULT_TRIGGER,
        help=(
            "Context that selects which checks are required. Default: %(default)s. "
            "push requires docker publish; pr requires docs-check and treats "
            "docker as not-applicable; manual requires every runnable gate "
            "except PR-only docs-check, including e2e."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="owner/repo to query (default: derived from `gh repo view`).",
    )
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="CHECK",
        help=(
            "Require an additional check regardless of trigger (repeatable), "
            "e.g. --require analyze for a main-target CodeQL gate. For the "
            "CodeQL matrix, 'analyze' matches every real check run whose name "
            "starts with 'Analyze (' and requires all of them to succeed."
        ),
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="CHECK",
        help="Exclude a check by job name from the required set (repeatable).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    sha = args.sha.strip()
    if not sha:
        print("error: commit SHA must not be empty", file=sys.stderr)
        return EXIT_ENV_ERROR

    try:
        repo = resolve_repo(args.repo)
        # Resolve a short SHA to its canonical full SHA (read-only commit
        # lookup) so the check-runs query, the head_sha exact-commit guard, and
        # the report all use one canonical SHA.
        if len(sha) != 40:
            sha = resolve_commit_sha(repo, sha)
        runs = fetch_check_runs(repo, sha)
    except GhNotInstalledError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENV_ERROR
    except GhInvocationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENV_ERROR
    except MalformedResponseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENV_ERROR

    report = validate_checks(
        sha,
        runs,
        args.trigger,
        require=set(args.require),
        skip=set(args.skip),
    )
    print(_format_report(report, sha, args.trigger))

    if report.wrong_commit_runs:
        print(
            "\nFAILURE: the API returned runs for a different commit — refusing to validate against a mismatched SHA.",
            file=sys.stderr,
        )
        return EXIT_VALIDATION_FAILED

    if not report.ok:
        print("\nFAILURE: not all required checks succeeded.", file=sys.stderr)
        return EXIT_VALIDATION_FAILED

    print("\nOK: all required checks completed successfully for this commit.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
