"""Static proof that deferred row-mirror evidence is explicitly wired to CI.

The capability manifest is a fixture under ``tests/unit/architecture/`` (moved out
of the globally gitignored ``artifacts/`` tree by D3B). It is placed under ``tests/``
and is not covered by any gitignore rule, so it is tracked on commit (pre-commit it is
currently untracked). On a clean checkout the fixture is present, so these wiring gates
hold without depending on an ignored, absent artifact.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
WORKFLOW = ROOT / ".github/workflows/backend-tests.yml"
MANIFEST = ROOT / "tests/unit/architecture/capability-manifest.json"
# The legacy, globally-gitignored location that must no longer be authoritative.
IGNORED_MANIFEST = (
    ROOT / "artifacts" / "designs" / "parts" / "song-row-mirror-leaks-into-domain" / "capability-manifest.json"
)


def _is_disabling_if(value: object) -> bool:
    """Return True if an ``if:`` value disables a step/job.

    YAML parses a bare ``if: false`` as bool False and ``if: ${{ false }}`` as a
    non-'false' string, so normalizing strings is required. The legitimate
    cache-hit guard (``steps.cache-venv.outputs.cache-hit != 'true'``) must
    return False.
    """
    if value is False or value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"false", "${{ false }}", "${{false}}"}
    return False


@pytest.mark.unit
def test_deferred_capability_manifest_is_machine_readable() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["ci_job"] == "database-tests"
    assert manifest["marker"] == "requires_database"
    assert "LOCAL_UNAVAILABLE" in manifest["evidence_policy"]["local_unavailable"].upper()
    assert "CI_DEFERRED" in manifest["evidence_policy"]["ci_deferred"].upper()
    assert "local pass" not in manifest["evidence_policy"]["ci_deferred"].lower()
    assert "local pass" in manifest["evidence_policy"]["ci_pass"].lower()
    # Exact set (not a superset): this both enumerates the required matrix and
    # prevents silent reintroduction of a removed/unsupported capability such as
    # the previously-claimed `approved-decoder` (removed by D3A P1-S5).
    assert set(manifest["required_matrix"]) == {
        "PostgreSQL",
        "transaction",
        "rollback",
        "concurrency",
        "SQLSTATE",
        "UUID-locator",
        "mood-marker",
        "mood-batch",
        "ambiguous-commit",
        "commit-ack-drop",
        "connection-loss",
    }
    # D3D-B closure: the deterministic D3D-A fault harness now covers the
    # previously-unreproducible pgcode-less commit-ack-drop (D3A-D2) and
    # connection-loss (D3A-D3) capabilities, so both are in the covered matrix
    # and their D3B blocked entries are removed. D3A-D1 is likewise not blocked:
    # it is resolved by the separate D2R-B single-winner plan (recorded under
    # resolved_by_other_plans below), not by D3D-B.
    assert "connection-loss" in manifest["required_matrix"]
    assert "commit-ack-drop" in manifest["required_matrix"]
    blocked = {entry["id"]: entry for entry in manifest["blocked_capabilities"]}
    assert "D3A-D1" not in blocked
    assert "D3A-D2" not in blocked
    assert "D3A-D3" not in blocked
    # D3A-D1 is resolved by D2R-B (distinct from D3D-B closure): the manifest
    # records it under resolved_by_other_plans with the D2R-B evidence node.
    d2rb_resolved = {entry["id"]: entry for entry in manifest["resolved_by_other_plans"]}
    assert "D3A-D1" in d2rb_resolved
    assert d2rb_resolved["D3A-D1"]["status"] == "RESOLVED_BY_D2R_B"
    assert (
        d2rb_resolved["D3A-D1"]["evidence_node"]
        == "tests/characterization/test_mood_owner_pg.py::TestMoodConcurrencyAndReaddress::"
        "test_same_locator_concurrent_writers_are_single_winner"
    )
    for entry in blocked.values():
        assert entry["owner"]
        assert entry["stop_condition"]
    assert manifest["mood_suite_path"] in manifest["pytest_paths"]


@pytest.mark.unit
def test_manifest_fixture_is_not_gitignored_and_path_safe() -> None:
    """The active manifest is a path under ``tests/`` (not the ignored
    ``artifacts/`` tree) that is not gitignored and is path-safe, so a clean
    checkout still resolves it. Trackedness is not asserted here: the fixture is
    untracked until the wave commit, and a truthful name is preferred to an
    overstatement.
    """
    assert MANIFEST.is_file(), f"tracked capability-manifest fixture missing: {MANIFEST}"
    rel = MANIFEST.relative_to(ROOT)
    assert rel.parts[0] == "tests", f"active manifest must live under tests/: {rel}"
    assert "artifacts" not in rel.parts, f"active manifest must not live under artifacts/: {rel}"
    # The active reader (this module) must reference the tracked fixture, never
    # the ignored artifacts path: the ignored path is a distinct, non-authoritative
    # location and must not be the manifest under test.
    assert not IGNORED_MANIFEST.exists(), (
        "legacy ignored manifest must be retired (typed source of truth is the fixture)"
    )

    # The fixture is not covered by any gitignore rule (global or repo-local), so it
    # is version-controlled once committed. Skip only when git/repo is unavailable.
    if shutil.which("git") and (ROOT / ".git").exists():
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, f"tracked fixture {rel} is gitignored (git check-ignore rc={proc.returncode})"


@pytest.mark.unit
def test_database_workflow_explicitly_invokes_required_matrix() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)
    job = workflow["jobs"]["database-tests"]
    steps = "\n".join(step.get("run", "") for step in job["steps"])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    command = manifest["exact_command"]

    # Exact equality against the manifest command, not substring containment: an
    # appended path/flag (e.g. a widened or narrowed collection set) must fail.
    # Strip the `source .venv/bin/activate` wrapper line so the pytest invocation
    # itself is compared verbatim. Compare the SET of pytest invocations against
    # the manifest's exact_command singleton, so an ADDITIONAL pytest line added
    # anywhere in the job (a second, unreviewed invocation) also fails this test.
    pytest_commands = {
        line.strip()
        for step in job["steps"]
        for line in step.get("run", "").splitlines()
        if line.strip().startswith("pytest ")
    }
    assert pytest_commands == {command}, (
        "database-tests must contain exactly the manifest exact_command as its only "
        f"pytest invocation; got: {sorted(pytest_commands)!r}"
    )
    # No line other than the activate wrapper may be a bare `pytest` invocation
    # with a non-standard prefix (e.g. `python -m pytest`) either.
    other_pytest_lines = {
        line.strip()
        for step in job["steps"]
        for line in step.get("run", "").splitlines()
        if "pytest" in line.strip() and not line.strip().startswith("pytest ")
    }
    assert other_pytest_lines == set(), (
        f"unexpected additional pytest invocations in database-tests: {sorted(other_pytest_lines)!r}"
    )
    assert 'pip install -e ".[dev]"' in steps
    assert "docker version" in steps
    assert "tests/characterization/" in steps
    assert "tests/characterization/test_mood_owner_pg.py" in steps
    assert "tests/integration/test_library_uuid_locator_identity_pg.py" in steps
    assert "tests/integration/test_song_upsert_state_boundary_pg.py" in steps
    assert "tests/sabotage/test_no_facades_begin_transactions.py" in steps
    assert "-m requires_database" in steps
    assert "continue-on-error" not in workflow_text
    assert "not requires_database" not in steps
    # Every named deferred suite exists on disk.
    for pytest_path in manifest["pytest_paths"]:
        assert (ROOT / pytest_path).exists(), f"named deferred suite path missing: {pytest_path}"


@pytest.mark.unit
def test_d3_mood_owner_suite_is_discoverable_and_database_marked() -> None:
    """The D3 mood/marker suite exists, is DB-marked, and lives under a
    directory the `database-tests` job actually collects with `-m requires_database`.

    Static only: this proves the deferred capability is wired for CI collection,
    not that it ran. Runtime status remains CI_DEFERRED until GitHub executes it.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = "\n".join(step.get("run", "") for step in workflow["jobs"]["database-tests"]["steps"])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    suite_path = manifest["mood_suite_path"]
    suite_file = ROOT / suite_path

    assert suite_file.is_file(), f"mood/marker suite missing: {suite_path}"
    source = suite_file.read_text(encoding="utf-8")
    assert "pytest.mark.requires_database" in source
    assert "pytest.mark.characterization" in source
    # The manifest names a top-level path that the workflow command passes to pytest.
    assert suite_path in steps
    assert "tests/characterization/" in steps
    assert "-m requires_database" in steps
    assert "not requires_database" not in steps


@pytest.mark.unit
def test_workflow_has_named_required_jobs_and_no_hidden_database_gate() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert {"test", "architecture-qc", "database-tests"} <= set(jobs)
    # Stable check-run name: the required-check disposition in both the manifest
    # and scripts/validate_commit.py relies on an exact-name match
    # (`run_name == 'database-tests'`). A job-level `name:` override or a
    # `strategy.matrix` would silently rename the check-run (matrix expands to
    # `database-tests (n)`), invalidating the validator's exact-name match while
    # every id-based wiring assertion above stays green. Pin both here.
    assert "name" not in jobs["database-tests"], (
        "database-tests must not override its job-level name; the required-check "
        f"validator matches the literal name 'database-tests', got: {jobs['database-tests'].get('name')!r}"
    )
    assert "strategy" not in jobs["database-tests"], (
        "database-tests must not define a strategy (matrix would rename the check-run "
        f"to 'database-tests (n)'), got: {jobs['database-tests'].get('strategy')!r}"
    )
    assert jobs["database-tests"]["steps"][-1]["name"].startswith("Run PostgreSQL")
    # No job-level disable: the most realistic whole-job masking (`if: false` on
    # the job) would silently skip the required gate. PyYAML parses a bare
    # `if: false` as bool False, so only key absence proves there is no guard.
    assert "if" not in jobs["database-tests"]

    # No step-level disable. YAML parses `if: false` to bool False and
    # `if: ${{ false }}` to a non-'false' string, so the old `!= 'false'` check
    # was a no-op. Reject bool False/None and any string that normalizes to
    # false, while ALLOWING the legitimate cache-hit guard.
    for step in jobs["database-tests"]["steps"]:
        # A missing `if` is not a disabling guard; only an explicit `if:` that
        # evaluates falsy disables the step.
        if "if" not in step:
            continue
        if_value = step["if"]
        assert not _is_disabling_if(if_value), f"step '{step.get('name')}' is disabled via if: {if_value!r}"
        # The only legitimate step-level condition is the cache-hit guard.
        assert "cache-venv.outputs.cache-hit" in str(if_value), f"unexpected step-level condition: {if_value!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        False,
        None,
        "false",
        "False",
        "FALSE",
        " false ",
        "${{ false }}",
        "${{false}}",
        "${{ FALSE }}",
    ],
)
def test_is_disabling_if_rejects_falsy_guards(value: object) -> None:
    """Negative control for the step-disable helper: every falsy spelling a
    workflow author might use to disable a required step must be flagged.

    These values never appear in the current clean workflow, so without this
    test the helper's rejecting branch has no coverage.
    """
    assert _is_disabling_if(value) is True, f"expected disabling guard for {value!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "steps.cache-venv.outputs.cache-hit != 'true'",
        "steps.cache-venv.outputs.cache-hit == 'false'",
        True,
        "true",
    ],
)
def test_is_disabling_if_allows_legitimate_guards(value: object) -> None:
    """The helper must not false-positive on the legitimate cache-hit guard or
    any other truthy condition."""
    assert _is_disabling_if(value) is False, f"expected allowed guard for {value!r}"


@pytest.mark.unit
def test_database_workflow_on_triggers_match_required_contract() -> None:
    """The workflow's own `on:` trigger/path filters must match the applicability
    the required-check contract assumes (P1-S6 trigger applicability).

    PyYAML parses the bare key `on` as boolean True (YAML 1.1), so read both
    spellings.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict), f"workflow 'on' must be a mapping, got: {on!r}"

    expected_paths = {
        "nomarr/**",
        "tests/**",
        "frontend/**",
        "e2e/**",
        "dockerfile",
        "docker/compose.yaml",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "playwright.config.ts",
        ".github/workflows/backend-tests.yml",
    }

    push = on["push"]
    assert set(push["branches"]) == {"main", "develop", "feat/**"}
    # `BASE_VERSION` bumps are push-only; the PR filter omits it.
    assert set(push["paths"]) == expected_paths | {"BASE_VERSION"}

    pr = on["pull_request"]
    assert set(pr["branches"]) == {"main", "develop"}
    assert set(pr["paths"]) == expected_paths

    assert "workflow_dispatch" in on


@pytest.mark.unit
def test_q3a_boundary_suite_is_wired_and_database_marked() -> None:
    """The Q3-A create-only boundary suite is DB-marked and explicitly wired.

    Static only: the suite path is named in the manifest and in the
    ``database-tests`` step, and its source carries ``requires_database``. This
    proves the deferred capability is wired for CI collection, not that it ran;
    runtime status remains CI_DEFERRED until GitHub executes it.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = "\n".join(step.get("run", "") for step in workflow["jobs"]["database-tests"]["steps"])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    suite_path = "tests/integration/test_song_upsert_state_boundary_pg.py"
    suite_file = ROOT / suite_path

    assert suite_file.is_file(), f"Q3-A boundary suite missing: {suite_path}"
    assert suite_path in manifest["pytest_paths"]
    assert suite_path in manifest["exact_command"]
    # The exact-equality gate above already pins the workflow command to the
    # manifest exact_command; assert the path is physically present too.
    assert suite_path in steps
    source = suite_file.read_text(encoding="utf-8")
    assert "pytest.mark.requires_database" in source
    assert "-m requires_database" in steps
    assert "not requires_database" not in steps
