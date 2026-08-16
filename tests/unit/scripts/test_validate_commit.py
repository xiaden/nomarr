"""Tests for scripts/validate_commit.py — exact-commit CI completion validator.

All tests run against mocked ``gh`` output at the subprocess boundary
(``subprocess.run`` / ``shutil.which``); nothing contacts GitHub. The validator's
own contract and state logic are exercised directly via ``validate_checks``, and
the CLI/exit-code behavior is exercised end-to-end via ``main`` with
``subprocess.run`` mocked to return canned API payloads.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from scripts.validate_commit import (
    EXIT_ENV_ERROR,
    EXIT_OK,
    EXIT_VALIDATION_FAILED,
    REQUIRED_CHECKS,
    MalformedResponseError,
    Report,
    _format_report,
    main,
    resolve_commit_sha,
    validate_checks,
)

# A full 40-char SHA that stands in for any requested commit in tests.
SHA = "4cda413a1bab82986a20a0296ba3bf75303d88ba"
# A different SHA used to exercise the exact-commit (wrong-commit) guard.
OTHER_SHA = "1111111111111111111111111111111111111111"

# The required checks under the default ``push`` trigger.
PUSH_REQUIRED = sorted(name for name, spec in REQUIRED_CHECKS.items() if "push" in spec.triggers)

# The required checks under the ``pr`` trigger.
PR_REQUIRED = sorted(name for name, spec in REQUIRED_CHECKS.items() if "pr" in spec.triggers)


def _check(
    name: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    head_sha: str | None = SHA,
) -> dict:
    """Build a single check-run object with the exact-commit SHA by default."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "app": {"slug": "github-actions"},
    }


def _payload(runs: list[dict]) -> str:
    """Serialise a check-runs API response body."""
    return json.dumps({"total_count": len(runs), "check_runs": runs})


def _green_for(name: str) -> dict:
    """Build a passing run for one contract key (exact job-name match)."""
    return _check(name)


# Realistic CodeQL matrix legs: codeql.yml's `analyze` job declares
# `name: Analyze (${{ matrix.language }})` with languages actions, go,
# javascript-typescript, python. GitHub therefore reports these check-run names,
# never a bare `analyze` — the validator's prefix-aware matcher must consume them.
ANALYZE_MATRIX_NAMES = [
    "Analyze (actions)",
    "Analyze (go)",
    "Analyze (javascript-typescript)",
    "Analyze (python)",
]


def _analyze_green() -> list[dict]:
    """Build the passing CodeQL matrix (one run per language leg)."""
    return [_check(name) for name in ANALYZE_MATRIX_NAMES]


def _all_green(names: list[str] | None = None) -> list[dict]:
    """A fully-passing set of check runs (defaults to every contract check)."""
    names = names if names is not None else sorted(REQUIRED_CHECKS)
    runs: list[dict] = []
    for name in names:
        if name == "analyze":
            runs.extend(_analyze_green())
        else:
            runs.append(_green_for(name))
    return runs


def _completed_result(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    """Build a canned CompletedProcess for a mocked ``gh api`` call."""
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# Pure contract/logic tests (no subprocess mocking) — validate_checks()
# ---------------------------------------------------------------------------


class TestValidateChecksSuccess:
    @pytest.mark.unit
    def test_push_all_green(self) -> None:
        report = validate_checks(SHA, _all_green(), "push")
        assert report.ok is True
        states = {r.name: r.state for r in report.results}
        assert all(states[name] == "PASS" for name in PUSH_REQUIRED)
        # e2e, docs-check, analyze are NOT-APPLICABLE on a push, never silently success.
        assert states["e2e"] == "NOT-APPLICABLE"
        assert states["docs-check"] == "NOT-APPLICABLE"
        assert states["analyze"] == "NOT-APPLICABLE"
        assert report.wrong_commit_runs == []
        assert report.extra_runs == []

    @pytest.mark.unit
    def test_pr_all_green_includes_docs_check(self) -> None:
        report = validate_checks(SHA, _all_green(), "pr")
        assert report.ok is True
        states = {r.name: r.state for r in report.results}
        assert states["docs-check"] == "PASS"
        # Docker publish is NOT-APPLICABLE on a PR (no image published).
        assert states["build-and-push"] == "NOT-APPLICABLE"
        assert states["promote"] == "NOT-APPLICABLE"


class TestValidateChecksMissing:
    @pytest.mark.unit
    def test_missing_required_check_reported(self) -> None:
        runs = [r for r in _all_green() if r["name"] != "test"]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        result = next(r for r in report.results if r.name == "test")
        assert result.state == "MISSING"
        assert "no matching run" in result.detail

    @pytest.mark.unit
    def test_empty_run_list_marks_all_required_missing(self) -> None:
        report = validate_checks(SHA, [], "push")
        assert report.ok is False
        assert all(r.state == "MISSING" for r in report.results if r.state != "NOT-APPLICABLE")


class TestValidateChecksWrongCommit:
    @pytest.mark.unit
    def test_wrong_head_sha_flags_exact_commit_violation(self) -> None:
        runs = _all_green()
        runs.append(_check("test", head_sha=OTHER_SHA))
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        assert len(report.wrong_commit_runs) == 1

    @pytest.mark.unit
    def test_all_wrong_head_sha_flags_every_run(self) -> None:
        runs = [_check(name, head_sha=OTHER_SHA) for name in sorted(REQUIRED_CHECKS)]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        assert len(report.wrong_commit_runs) == len(runs)

    @pytest.mark.unit
    def test_missing_head_sha_flags_exact_commit_violation(self) -> None:
        # A run with no head_sha is outside the exact-commit contract: fail
        # closed rather than silently counting as a PASS.
        runs = _all_green()
        runs.append(_check("test", head_sha=None))
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        assert len(report.wrong_commit_runs) == 1
        result = next(r for r in report.results if r.name == "test")
        assert result.state == "FAIL"


class TestValidateChecksUnsuccessfulConclusions:
    @pytest.mark.unit
    def test_pending_check_fails(self) -> None:
        runs = [
            _check(name) if name != "lint" else _check("lint", status="in_progress", conclusion=None)
            for name in sorted(REQUIRED_CHECKS)
        ]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        result = next(r for r in report.results if r.name == "lint")
        assert result.state == "FAIL"
        assert "pending" in result.detail

    @pytest.mark.unit
    def test_failed_check_fails(self) -> None:
        runs = [
            _check(name) if name != "deptry" else _check("deptry", conclusion="failure")
            for name in sorted(REQUIRED_CHECKS)
        ]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        result = next(r for r in report.results if r.name == "deptry")
        assert result.state == "FAIL"
        assert "not success" in result.detail

    @pytest.mark.unit
    @pytest.mark.parametrize("conclusion", ["cancelled", "skipped"])
    def test_cancelled_or_skipped_fails(self, conclusion: str) -> None:
        runs = [
            _check(name) if name != "test" else _check("test", conclusion=conclusion)
            for name in sorted(REQUIRED_CHECKS)
        ]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False
        result = next(r for r in report.results if r.name == "test")
        assert result.state == "FAIL"

    @pytest.mark.unit
    def test_neutral_is_not_success(self) -> None:
        runs = [
            _check(name) if name != "frontend-checks" else _check("frontend-checks", conclusion="neutral")
            for name in sorted(REQUIRED_CHECKS)
        ]
        report = validate_checks(SHA, runs, "push")
        assert report.ok is False


class TestRequireSkipFlags:
    @pytest.mark.unit
    def test_require_analyze_makes_codeql_required(self) -> None:
        # `_all_green` yields the realistic matrix legs (`Analyze (python)` ...)
        # alongside the other contract keys; requiring `analyze` must consume
        # every matrix leg and PASS.
        runs = _all_green()
        report = validate_checks(SHA, runs, "push", require={"analyze"})
        states = {r.name: r.state for r in report.results}
        assert states["analyze"] == "PASS"
        assert report.extra_runs == []

    @pytest.mark.unit
    def test_require_missing_check_reports_missing(self) -> None:
        # ``analyze`` is required but every matrix leg is absent from the payload.
        runs = [r for r in _all_green() if not r["name"].startswith("Analyze (")]
        report = validate_checks(SHA, runs, "push", require={"analyze"})
        assert report.ok is False
        assert states_missing(report, "analyze")

    @pytest.mark.unit
    def test_skip_removes_check_from_required_set(self) -> None:
        # Skipping ``promote`` turns it NOT-APPLICABLE even on a push.
        report = validate_checks(SHA, _all_green(), "push", skip={"promote"})
        states = {r.name: r.state for r in report.results}
        assert states["promote"] == "NOT-APPLICABLE"


class TestCodeQlMatrixMatching:
    """The CodeQL `analyze` contract uses a prefix-aware matcher against the
    real matrix check-run names (`Analyze (actions)`, `Analyze (python)`, ...),
    not the bare job id `analyze`."""

    @pytest.mark.unit
    def test_all_matrix_legs_pass_when_required(self) -> None:
        runs = _all_green()
        report = validate_checks(SHA, runs, "pr", require={"analyze"})
        assert report.ok is True
        result = next(r for r in report.results if r.name == "analyze")
        assert result.state == "PASS"

    @pytest.mark.unit
    def test_partial_matrix_missing_leg_fails(self) -> None:
        # Drop one language leg (`Analyze (go)`); the rest pass. Because the
        # prefix matcher consumes the family as a unit, a missing leg is a FAIL.
        runs = [r for r in _all_green() if r["name"] != "Analyze (go)"]
        report = validate_checks(SHA, runs, "pr", require={"analyze"})
        assert report.ok is False
        result = next(r for r in report.results if r.name == "analyze")
        assert result.state == "FAIL"
        assert "Analyze (go)" in result.detail

    @pytest.mark.unit
    def test_a_failed_matrix_leg_fails(self) -> None:
        runs = [r for r in _all_green() if r["name"] != "Analyze (python)"]
        runs.append(_check("Analyze (python)", conclusion="failure"))
        report = validate_checks(SHA, runs, "pr", require={"analyze"})
        assert report.ok is False
        result = next(r for r in report.results if r.name == "analyze")
        assert result.state == "FAIL"
        assert "Analyze (python)" in result.detail
        assert "not success" in result.detail

    @pytest.mark.unit
    def test_bare_analyze_run_does_not_satisfy_matrix(self) -> None:
        # A check named exactly `analyze` (the job id) is NOT how GitHub names
        # the CodeQL matrix runs; the prefix matcher must not accept it.
        runs = [r for r in _all_green() if not r["name"].startswith("Analyze (")]
        runs.append(_check("analyze"))
        report = validate_checks(SHA, runs, "pr", require={"analyze"})
        assert report.ok is False
        assert states_missing(report, "analyze")

    @pytest.mark.unit
    def test_codeql_matrix_runs_are_not_extra(self) -> None:
        # The matrix legs are consumed by the analyze contract entry, so they
        # must never be reported as uncategorized (extra) runs.
        report = validate_checks(SHA, _all_green(), "push")
        assert report.ok is True
        assert report.extra_runs == []

    @pytest.mark.unit
    def test_not_required_analyze_reports_not_applicable(self) -> None:
        # On a plain push without --require analyze, the matrix runs are present
        # but analyze stays NOT-APPLICABLE (CodeQL is main-target only).
        report = validate_checks(SHA, _all_green(), "push")
        states = {r.name: r.state for r in report.results}
        assert states["analyze"] == "NOT-APPLICABLE"


def states_missing(report: Report, name: str) -> bool:
    result = next((r for r in report.results if r.name == name), None)
    return result is not None and result.state == "MISSING"


# ---------------------------------------------------------------------------
# CLI / exit-code tests — mocked at the subprocess boundary via main()
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.mark.unit
    def test_success_exit_zero(self) -> None:
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(_all_green()))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_OK

    @pytest.mark.unit
    def test_missing_check_exits_nonzero(self) -> None:
        runs = [r for r in _all_green() if r["name"] != "test"]
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(runs))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_VALIDATION_FAILED

    @pytest.mark.unit
    def test_wrong_commit_exits_nonzero(self) -> None:
        runs = [_check(name, head_sha=OTHER_SHA) for name in sorted(REQUIRED_CHECKS)]
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(runs))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_VALIDATION_FAILED

    @pytest.mark.unit
    def test_pending_exits_nonzero(self) -> None:
        runs = [
            _check(name) if name != "lint" else _check("lint", status="in_progress", conclusion=None)
            for name in sorted(REQUIRED_CHECKS)
        ]
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(runs))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_VALIDATION_FAILED

    @pytest.mark.unit
    def test_failed_exits_nonzero(self) -> None:
        runs = [
            _check(name) if name != "test" else _check("test", conclusion="failure") for name in sorted(REQUIRED_CHECKS)
        ]
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(runs))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_VALIDATION_FAILED

    @pytest.mark.unit
    @pytest.mark.parametrize("conclusion", ["cancelled", "skipped"])
    def test_cancelled_or_skipped_exits_nonzero(self, conclusion: str) -> None:
        runs = [
            _check(name) if name != "frontend-checks" else _check("frontend-checks", conclusion=conclusion)
            for name in sorted(REQUIRED_CHECKS)
        ]
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(_payload(runs))):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_VALIDATION_FAILED

    @pytest.mark.unit
    def test_malformed_json_exits_env_error(self) -> None:
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result("not json")):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_ENV_ERROR

    @pytest.mark.unit
    def test_malformed_missing_check_runs_key_exits_env_error(self) -> None:
        bad = json.dumps({"total_count": 0})  # no "check_runs" key
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(bad)):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_ENV_ERROR

    @pytest.mark.unit
    def test_gh_invocation_failure_exits_env_error(self) -> None:
        proc = subprocess.CompletedProcess(args=["gh"], returncode=1, stdout="", stderr="boom")
        with patch("scripts.validate_commit.subprocess.run", return_value=proc):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_ENV_ERROR

    @pytest.mark.unit
    def test_missing_gh_cli_exits_env_error(self) -> None:
        with patch("scripts.validate_commit.shutil.which", return_value=None):
            code = main([SHA, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_ENV_ERROR

    @pytest.mark.unit
    def test_empty_sha_exits_env_error(self) -> None:
        code = main(["   "])
        assert code == EXIT_ENV_ERROR

    @pytest.mark.unit
    def test_repo_view_resolution_when_no_repo_flag(self) -> None:
        # Without --repo, the validator runs `gh repo view` first, then the
        # check-runs API. Mock subprocess.run to dispatch on the gh subcommand.
        def fake_run(args, **kwargs):
            if args[:2] == ["gh", "repo"]:
                return _completed_result("xiaden/nomarr")
            return _completed_result(_payload(_all_green()))

        with patch("scripts.validate_commit.subprocess.run", side_effect=fake_run):
            code = main([SHA, "--trigger", "push"])
        assert code == EXIT_OK


class TestShortShaResolution:
    """Short SHAs are resolved to the canonical full SHA via a read-only
    ``gh api repos/{owner}/{repo}/commits/{sha}`` GET before the check-runs
    query; exact validation and reporting use the canonical SHA. All tests are
    offline — the only contact is a mocked ``gh`` subprocess."""

    SHORT = "4cda413"

    @pytest.mark.unit
    def test_resolve_commit_sha_returns_canonical_full_sha(self) -> None:
        commit = json.dumps({"sha": SHA, "commit": {"message": "x"}})
        with patch("scripts.validate_commit.subprocess.run", return_value=_completed_result(commit)):
            assert resolve_commit_sha("xiaden/nomarr", self.SHORT) == SHA

    @pytest.mark.unit
    def test_resolve_commit_sha_malformed_response_raises(self) -> None:
        with (
            patch("scripts.validate_commit.subprocess.run", return_value=_completed_result("not json")),
            pytest.raises(MalformedResponseError),
        ):
            resolve_commit_sha("xiaden/nomarr", self.SHORT)

    @pytest.mark.unit
    def test_short_sha_resolved_before_check_runs_cli(self) -> None:
        # Regression: a short SHA previously went straight to the check-runs
        # endpoint, which returns runs whose head_sha is the *full* SHA — a
        # misleading EXACT-COMMIT VIOLATION. Now the short SHA is resolved to
        # the canonical full SHA first (read-only commits GET), and the
        # check-runs query plus exact-commit guard use the canonical SHA.
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs):
            calls.append(list(args))
            if args[:2] == ["gh", "api"]:
                endpoint = args[2]
                if "/check-runs" in endpoint:
                    # The check-runs query must use the canonical full SHA.
                    assert endpoint == f"repos/xiaden/nomarr/commits/{SHA}/check-runs"
                    return _completed_result(_payload(_all_green()))
                if endpoint.startswith("repos/xiaden/nomarr/commits/") and not endpoint.endswith("/check-runs"):
                    # The resolution call uses the short SHA the user passed.
                    assert endpoint == f"repos/xiaden/nomarr/commits/{self.SHORT}"
                    return _completed_result(json.dumps({"sha": SHA}))
            raise AssertionError(f"unexpected gh call: {args}")

        with patch("scripts.validate_commit.subprocess.run", side_effect=fake_run):
            code = main([self.SHORT, "--trigger", "push", "--repo", "xiaden/nomarr"])
        assert code == EXIT_OK
        assert len(calls) == 2


class TestFormatReport:
    @pytest.mark.unit
    def test_ok_report_contains_summary(self) -> None:
        report = validate_checks(SHA, _all_green(), "push")
        text = _format_report(report, SHA, "push")
        assert "Validating commit" in text
        assert "OK" not in text  # the OK line is added by main(), not _format_report

    @pytest.mark.unit
    def test_wrong_commit_report_explicit(self) -> None:
        runs = [_check(name, head_sha=OTHER_SHA) for name in sorted(REQUIRED_CHECKS)]
        report = validate_checks(SHA, runs, "push")
        text = _format_report(report, SHA, "push")
        assert "EXACT-COMMIT VIOLATION" in text
        assert OTHER_SHA in text
