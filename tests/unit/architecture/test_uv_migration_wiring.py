"""Static gate that the CI dependency installation migrated to uv.

Authored spec-first during Phase 1 of the uv sole-package-manager migration;
after the completed Phase 2 workflow migration these assertions hold GREEN
against the migrated uv workflows. They encode the target state — uv dependency
groups in ``pyproject.toml``, a committed ``.python-version``, ``uv sync
--locked`` instead of the pip-era ``python -m venv``/``pip install`` block,
``requirements.txt`` removed from the workflow ``paths:`` filters, one
``uv.lock`` carrying both ONNX distributions, and the immutable required job
names.

Static only: it reads ``pyproject.toml``, ``uv.lock``, ``.python-version``, and
the two backend workflow files; it never executes a package manager.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
PYTHON_VERSION_FILE = ROOT / ".python-version"
BACKEND_QUALITY = ROOT / ".github/workflows/backend-quality.yml"
BACKEND_TESTS = ROOT / ".github/workflows/backend-tests.yml"
BACKEND_WORKFLOWS = (BACKEND_QUALITY, BACKEND_TESTS)

REQUIRED_JOB_NAMES = frozenset({"lint", "deptry", "test", "architecture-qc", "database-tests"})
FORBIDDEN_INSTALL_FRAGMENTS = (
    "pip install",
    "python -m venv",
    "pip install --upgrade pip",
)

# --- uv CI install contract (binding contract C4) -------------------------
# Every required backend job installs dependencies through a pinned, immutable
# setup-uv action and a locked ``uv sync --locked``, with the system Python
# selected via ``.python-version`` and uv forbidden from downloading its own
# interpreter. These pins are asserted per job so a missing/renamed action in a
# single job cannot slip through.
SETUP_UV_ACTION = "astral-sh/setup-uv@v10.1.0"
SETUP_UV_VERSION = "0.12.13"
SETUP_PYTHON_ACTION = "actions/setup-python@v6"
SETUP_PYTHON_VERSION_FILE = ".python-version"
UV_JOB_ENV = {
    "UV_PYTHON_PREFERENCE": "only-system",
    "UV_PYTHON_DOWNLOADS": "never",
}
# A moving ref such as ``@v10`` or ``@v10.1`` floats; only a full
# ``vMAJOR.MINOR.PATCH`` tag is immutable.
FULL_IMMUTABLE_REF = re.compile(r"^v\d+\.\d+\.\d+$")

# (workflow file, required job) pairs carrying the uv install contract.
JOB_WORKFLOW_PAIRS = (
    (BACKEND_QUALITY, "lint"),
    (BACKEND_QUALITY, "deptry"),
    (BACKEND_TESTS, "test"),
    (BACKEND_TESTS, "architecture-qc"),
    (BACKEND_TESTS, "database-tests"),
)
JOB_WORKFLOW_IDS = [f"{path.name}::{job}" for path, job in JOB_WORKFLOW_PAIRS]


def _job(workflow_path: Path, job_name: str) -> dict:
    jobs = _load_yaml(workflow_path).get("jobs", {})
    assert job_name in jobs, f"{workflow_path.name} is missing required job '{job_name}'"
    return jobs[job_name]


def _job_steps(workflow_path: Path, job_name: str) -> list[dict]:
    return _job(workflow_path, job_name).get("steps", [])


def _run_lines(steps: list[dict]) -> list[str]:
    return [line.strip() for step in steps for line in (step.get("run") or "").splitlines()]


def _job_run_blocks(steps: list[dict]) -> list[str]:
    return [step.get("run") or "" for step in steps if "run" in step]


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} did not parse as a mapping"
    return data


def _on(workflow: dict) -> dict:
    """Return the ``on:`` mapping.

    PyYAML parses the bare ``on`` key as boolean True (YAML 1.1), so read both
    spellings.
    """
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict), f"workflow 'on' must be a mapping, got {on!r}"
    return on


def _run_blocks(workflow: dict) -> list[str]:
    return [
        step.get("run", "")
        for job in workflow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if "run" in step
    ]


@pytest.mark.unit
def test_pyproject_declares_dev_cpu_gpu_dependency_groups() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    groups = pyproject.get("dependency-groups", {})
    assert {"dev", "cpu", "gpu"} <= set(groups), (
        f"pyproject.toml must declare dev/cpu/gpu dependency groups; got {sorted(groups)!r}"
    )


@pytest.mark.unit
def test_pyproject_declares_uv_tool_configuration() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv = pyproject.get("tool", {}).get("uv", {})
    assert {"default-groups", "conflicts", "required-version"} <= set(uv), (
        f"[tool.uv] must configure default-groups/conflicts/required-version; got {sorted(uv)!r}"
    )
    # CPU is the dev/CI default so a plain `uv sync --locked` yields dev+cpu (R4/R6).
    assert set(uv["default-groups"]) >= {"dev", "cpu"}
    assert uv["required-version"].startswith(">=")
    assert uv["conflicts"]


@pytest.mark.unit
def test_python_version_file_pins_312() -> None:
    assert PYTHON_VERSION_FILE.is_file(), ".python-version must exist (R5)"
    assert PYTHON_VERSION_FILE.read_text(encoding="utf-8").strip() == "3.12"


@pytest.mark.unit
def test_backend_workflows_have_no_pip_install_or_venv_run_steps() -> None:
    offending = [
        f"{path.name}: {fragment!r}"
        for path in BACKEND_WORKFLOWS
        for run in _run_blocks(_load_yaml(path))
        for fragment in FORBIDDEN_INSTALL_FRAGMENTS
        if fragment in run
    ]
    assert offending == [], f"pip-era install machinery must be removed (R8): {offending}"


@pytest.mark.unit
def test_backend_workflow_paths_drop_requirements_and_add_python_version() -> None:
    for path in BACKEND_WORKFLOWS:
        workflow = _load_yaml(path)
        on = _on(workflow)
        for trigger in ("push", "pull_request"):
            paths = set(on[trigger]["paths"])
            assert "requirements.txt" not in paths, (
                f"{path.name} {trigger}: requirements.txt is deleted; drop it from paths (R16)"
            )
            assert ".python-version" in paths, f"{path.name} {trigger}: add .python-version to paths (R16)"


@pytest.mark.unit
def test_uv_lock_contains_both_onnx_distributions() -> None:
    lock_text = UV_LOCK.read_text(encoding="utf-8")
    assert 'name = "onnxruntime"' in lock_text, "uv.lock must resolve the CPU onnxruntime (R6)"
    assert 'name = "onnxruntime-gpu"' in lock_text, "uv.lock must resolve the GPU onnxruntime-gpu (R6)"


@pytest.mark.unit
def test_backend_workflows_preserve_required_job_names() -> None:
    quality = _load_yaml(BACKEND_QUALITY)
    tests = _load_yaml(BACKEND_TESTS)
    quality_jobs = set(quality.get("jobs", {}))
    test_jobs = set(tests.get("jobs", {}))
    assert {"lint", "deptry"} <= quality_jobs, (
        f"backend-quality.yml must keep jobs lint/deptry; got {sorted(quality_jobs)!r}"
    )
    assert {"test", "architecture-qc", "database-tests"} <= test_jobs, (
        f"backend-tests.yml must keep jobs test/architecture-qc/database-tests; got {sorted(test_jobs)!r}"
    )
    assert quality_jobs | test_jobs >= REQUIRED_JOB_NAMES, (
        f"required CI job names must be preserved (R9); got {sorted(quality_jobs | test_jobs)!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("workflow_path", "job_name"),
    JOB_WORKFLOW_PAIRS,
    ids=JOB_WORKFLOW_IDS,
)
def test_each_required_job_pins_setup_uv_to_full_immutable_tag(workflow_path: Path, job_name: str) -> None:
    """Every required backend job installs uv through the exact immutable pin.

    Contract C4 pins ``astral-sh/setup-uv@v10.1.0`` with ``version: 0.12.13`` in
    all five jobs. A moving ``@v10``/``@v10.1`` ref (or a missing/renamed action
    in one job) would let the install tool float and must fail.
    """
    setup_uv_steps = [
        step
        for step in _job_steps(workflow_path, job_name)
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]
    assert len(setup_uv_steps) == 1, (
        f"{workflow_path.name}:{job_name} must have exactly one astral-sh/setup-uv step; got {len(setup_uv_steps)}"
    )
    step = setup_uv_steps[0]
    assert step["uses"] == SETUP_UV_ACTION, (
        f"{workflow_path.name}:{job_name} setup-uv must be pinned to {SETUP_UV_ACTION!r}; got {step['uses']!r}"
    )
    assert step.get("with", {}).get("version") == SETUP_UV_VERSION, (
        f"{workflow_path.name}:{job_name} setup-uv version must be {SETUP_UV_VERSION!r}; "
        f"got {step.get('with', {}).get('version')!r}"
    )
    ref = step["uses"].rpartition("@")[2]
    assert FULL_IMMUTABLE_REF.match(ref), (
        f"{workflow_path.name}:{job_name} setup-uv ref must be a full immutable "
        f"vMAJOR.MINOR.PATCH tag (a moving @v10/@v10.1 ref floats); got '@{ref}'"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("workflow_path", "job_name"),
    JOB_WORKFLOW_PAIRS,
    ids=JOB_WORKFLOW_IDS,
)
def test_each_required_job_setup_python_uses_version_file(workflow_path: Path, job_name: str) -> None:
    """Every required backend job selects the interpreter via ``.python-version``."""
    setup_python_steps = [
        step for step in _job_steps(workflow_path, job_name) if step.get("uses") == SETUP_PYTHON_ACTION
    ]
    assert len(setup_python_steps) == 1, (
        f"{workflow_path.name}:{job_name} must have exactly one {SETUP_PYTHON_ACTION} step; "
        f"got {len(setup_python_steps)}"
    )
    version_file = setup_python_steps[0].get("with", {}).get("python-version-file")
    assert version_file == SETUP_PYTHON_VERSION_FILE, (
        f"{workflow_path.name}:{job_name} setup-python must use "
        f"python-version-file={SETUP_PYTHON_VERSION_FILE!r}; got {version_file!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("workflow_path", "job_name"),
    JOB_WORKFLOW_PAIRS,
    ids=JOB_WORKFLOW_IDS,
)
def test_each_required_job_pins_uv_python_env(workflow_path: Path, job_name: str) -> None:
    """Every required backend job forbids uv interpreter downloads and requires system Python."""
    env = _job(workflow_path, job_name).get("env", {})
    assert isinstance(env, dict), f"{workflow_path.name}:{job_name} env must be a mapping; got {env!r}"
    for key, expected in UV_JOB_ENV.items():
        assert env.get(key) == expected, (
            f"{workflow_path.name}:{job_name} env[{key!r}] must be {expected!r}; got {env.get(key)!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("workflow_path", "job_name"),
    JOB_WORKFLOW_PAIRS,
    ids=JOB_WORKFLOW_IDS,
)
def test_each_required_job_installs_with_locked_uv_sync(workflow_path: Path, job_name: str) -> None:
    """Every required backend job installs with exactly ``uv sync --locked``.

    Also asserts no bare (unlocked) ``uv sync`` run line exists, so a dropped
    ``--locked`` flag is caught. Previously only ``database-tests`` was covered.
    """
    steps = _job_steps(workflow_path, job_name)
    locked_blocks = [block for block in _job_run_blocks(steps) if block == "uv sync --locked"]
    assert len(locked_blocks) == 1, (
        f"{workflow_path.name}:{job_name} must run 'uv sync --locked' exactly once; got {locked_blocks!r}"
    )
    unlocked = [line for line in _run_lines(steps) if line == "uv sync"]
    assert unlocked == [], (
        f"{workflow_path.name}:{job_name} must not contain a bare unlocked 'uv sync' run line; got {unlocked!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("workflow_path", BACKEND_WORKFLOWS, ids=lambda path: path.name)
def test_backend_workflows_have_no_venv_actions_cache_remnant(workflow_path: Path) -> None:
    """Contract C4 deletes the pre-migration ``.venv`` ``actions/cache`` step.

    The existing negative test only checks pip/venv install fragments; this gate
    proves the cache step itself is gone and no ``cache-venv`` reference remains.
    """
    workflow = _load_yaml(workflow_path)
    cache_steps = [
        step
        for job in workflow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/cache")
    ]
    assert cache_steps == [], f"{workflow_path.name} must not retain an actions/cache step: {cache_steps!r}"
    text = workflow_path.read_text(encoding="utf-8")
    assert "cache-venv" not in text, f"{workflow_path.name} must not reference the removed cache-venv step"


@pytest.mark.unit
def test_backend_workflow_command_bodies_survive_activation() -> None:
    """The command bodies under ``source .venv/bin/activate`` stay byte-identical."""
    lint_lines = _run_lines(_job_steps(BACKEND_QUALITY, "lint"))
    for expected in (
        "ruff check .",
        "ruff format --check .",
        "mypy nomarr/ --config-file pyproject.toml",
        "lint-imports",
    ):
        assert expected in lint_lines, f"backend-quality.yml lint job must still run {expected!r}"

    deptry_lines = _run_lines(_job_steps(BACKEND_QUALITY, "deptry"))
    assert "deptry . --known-first-party nomarr" in deptry_lines, (
        "backend-quality.yml deptry job must still run 'deptry . --known-first-party nomarr'"
    )

    test_steps = _job_steps(BACKEND_TESTS, "test")
    test_lines = _run_lines(test_steps)
    assert 'pytest tests/ -v -m "not container_only and not requires_database and not code_smell"' in test_lines, (
        "backend-tests.yml test job must keep the exact pytest gate command"
    )
    assert any("libchromaprint1" in (step.get("run") or "") for step in test_steps), (
        "backend-tests.yml test job must keep the libchromaprint1 system dependency install"
    )
