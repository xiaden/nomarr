"""Static gate for Plan D's Docker base image + base-rebuild workflow wiring.

Static only: this test reads ``dockerfile.base``, ``dockerfile``,
``.github/workflows/build-base.yml``, and
``.github/workflows/docker-publish.yml`` and parses them as YAML / text. It
never invokes Docker and never executes a workflow.

It covers the reusable-workflow wiring — ``build-base.yml`` is a
``workflow_call``-able reusable workflow that is also manually dispatchable
(``workflow_dispatch``) and carries **no standalone ``push`` trigger** (Amendment
A2: ``docker-publish.yml`` is the single push-triggered base orchestrator),
``docker-publish.yml`` invoking it as a non-required ``build-base`` job that
gates ``build-and-push`` — and the pinned-uv base derivation (GPU dependency set
derived from ``pyproject.toml`` + ``uv.lock``, no pip/venv machinery,
system-Python exact sync).

``docker-publish.yml``'s ``build-base`` reusable-call job grants every
permission the callee (``build-base.yml``) declares, because GitHub reusable
workflows can only maintain or reduce permissions through the call chain and
never grant ``id-token``/``attestations`` by default. It also pins the consumed
``BASE_TAG`` by ref so the app is always built from the base the same-run
``build-base`` job published for this commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
DOCKERFILE_BASE = ROOT / "dockerfile.base"
DOCKERFILE_APP = ROOT / "dockerfile"
BUILD_BASE = ROOT / ".github/workflows/build-base.yml"
DOCKER_PUBLISH = ROOT / ".github/workflows/docker-publish.yml"


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


def _dockerfile_run_command(text: str, prefix: str) -> str:
    """Return the Dockerfile ``RUN`` instruction whose command starts with ``prefix``.

    The returned string is the logical command with line continuations joined, so
    assertions run against the command itself rather than whole-file text. This
    keeps them immune to the same token appearing in an explanatory comment.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("RUN ") or not line[len("RUN ") :].lstrip().startswith(prefix):
            continue
        command = [line[len("RUN ") :]]
        while command[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            command.append(lines[index])
        return " ".join(part.rstrip("\\").strip() for part in command)
    raise AssertionError(f"dockerfile.base has no RUN command starting with {prefix!r}")


def _dockerfile_env_values(text: str) -> str:
    """Return the joined body of every ``ENV`` instruction, comments excluded.

    Only lines belonging to an ``ENV`` instruction (its start line plus any
    ``\\`` continuations) are collected, so a token that also appears in a
    ``#`` explanatory comment cannot satisfy an assertion about the configured
    environment.
    """
    lines = text.splitlines()
    chunks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("ENV "):
            index += 1
            continue
        body = [line[len("ENV ") :]]
        while body[-1].rstrip().endswith("\\") and index + 1 < len(lines):
            index += 1
            body.append(lines[index])
        chunks.append(" ".join(part.rstrip("\\").strip() for part in body))
        index += 1
    assert chunks, "dockerfile.base must declare at least one ENV instruction"
    return " ".join(chunks)


@pytest.mark.unit
def test_build_base_is_reusable_and_manual_dispatch_only() -> None:
    on = _on(_load_yaml(BUILD_BASE))
    assert {"workflow_call", "workflow_dispatch"} <= set(on), (
        f"build-base.yml must be reusable and manually dispatchable; got {sorted(on)!r}"
    )
    assert "push" not in on, (
        "build-base.yml must not carry a standalone push trigger (Amendment A2: "
        f"docker-publish.yml is the single push-triggered base orchestrator); got push={on.get('push')!r}"
    )


@pytest.mark.unit
def test_build_base_job_preserves_attestation_build() -> None:
    workflow = _load_yaml(BUILD_BASE)
    jobs = workflow["jobs"]
    assert set(jobs) == {"build-base"}, f"build-base.yml must contain only the build-base job; got {sorted(jobs)!r}"
    job = jobs["build-base"]
    assert job["runs-on"] == "ubuntu-latest", f"build-base job must run on ubuntu-latest; got {job['runs-on']!r}"
    assert set(job["permissions"].items()) >= {
        ("contents", "read"),
        ("packages", "write"),
        ("id-token", "write"),
        ("attestations", "write"),
        ("artifact-metadata", "write"),
    }, f"build-base job must retain its attestation permissions; got {job['permissions']!r}"
    assert job["outputs"]["base_tag"] == "${{ steps.tags.outputs.base_tag }}"

    build_steps = [step for step in job["steps"] if step.get("uses", "").startswith("docker/build-push-action@")]
    assert len(build_steps) == 1, f"build-base job must have exactly one build-push step; got {len(build_steps)}"
    with_ = build_steps[0]["with"]
    assert with_["file"] == "./dockerfile.base", f"base build file must be ./dockerfile.base; got {with_['file']!r}"
    assert with_["push"] is True, f"base build must push; got {with_['push']!r}"
    assert with_["provenance"] is True, f"base build must emit provenance; got {with_['provenance']!r}"
    assert with_["sbom"] is True, f"base build must emit SBOM; got {with_['sbom']!r}"


@pytest.mark.unit
def test_docker_publish_calls_base_as_reusable_job() -> None:
    job = _load_yaml(DOCKER_PUBLISH)["jobs"]["build-base"]
    assert job["uses"] == "./.github/workflows/build-base.yml", (
        f"docker-publish build-base must call the reusable workflow; got {job.get('uses')!r}"
    )
    assert job["secrets"] == "inherit", f"docker-publish build-base must inherit secrets; got {job.get('secrets')!r}"
    assert "runs-on" not in job and "steps" not in job, (
        f"reusable-call job must not define runs-on/steps; got {sorted(job)!r}"
    )


@pytest.mark.unit
def test_docker_publish_orders_app_after_base_and_keeps_check_names() -> None:
    jobs = _load_yaml(DOCKER_PUBLISH)["jobs"]
    assert jobs["build-and-push"]["needs"] == ["policy", "build-base"], (
        f"build-and-push must run after build-base; got {jobs['build-and-push'].get('needs')!r}"
    )
    assert jobs["promote"]["needs"] == ["policy", "build-and-push"], (
        f"promote must depend on policy and build-and-push; got {jobs['promote'].get('needs')!r}"
    )
    assert {"build-and-push", "promote"} <= set(jobs), f"required check names must be preserved; got {sorted(jobs)!r}"


@pytest.mark.unit
def test_docker_publish_uses_release_policy_and_manual_dispatch() -> None:
    on = _on(_load_yaml(DOCKER_PUBLISH))
    assert on["push"] == {"tags": ["v*"]}
    assert "workflow_dispatch" in on, "docker-publish must remain manually dispatchable"
    assert on["workflow_dispatch"]["inputs"]["channel"]["required"] is True


@pytest.mark.unit
def test_docker_workflows_have_no_pip_or_venv_machinery() -> None:
    forbidden = ("pip install", "python -m venv", "pip install --upgrade pip")
    offending = [
        f"{path.name}: {fragment!r}"
        for path in (BUILD_BASE, DOCKER_PUBLISH)
        for run in _run_blocks(_load_yaml(path))
        for fragment in forbidden
        if fragment in run
    ]
    assert offending == [], f"pip-era install machinery must be absent from Docker workflows: {offending}"


@pytest.mark.unit
def test_docker_base_derives_gpu_set_from_lock_with_pinned_uv() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    assert re.search(r"ghcr\.io/astral-sh/uv:\d[^\s]*", text), (
        "dockerfile.base must copy uv from a version-pinned image tag"
    )
    assert "astral-sh/uv:latest" not in text, "dockerfile.base must not use the unbounded uv:latest tag"
    assert "COPY pyproject.toml uv.lock .python-version ./" in text, (
        "dockerfile.base must COPY the lockfile and interpreter pin for the export"
    )
    assert "uv export --frozen --no-default-groups --group gpu" in text, (
        "dockerfile.base must derive the GPU set from the lock with --no-default-groups --group gpu"
    )
    assert text.count("uv pip sync --system --break-system-packages") == 2, (
        "dockerfile.base must contain exactly one dry-run and one real exact sync"
    )
    assert "--dry-run" in text, "dockerfile.base must dry-run the exact sync before applying it"
    assert re.search(r"uv sync\b", text) is None, (
        "dockerfile.base must not run a project-level 'uv sync' (only 'uv pip sync')"
    )


@pytest.mark.unit
def test_docker_base_removes_pip_and_forbids_venv_env() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    for forbidden in ("pip install", "python3-pip", "PIP_NO_CACHE_DIR", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        assert forbidden not in text, f"dockerfile.base must not contain {forbidden!r}"
    env_values = _dockerfile_env_values(text)
    for required in ("UV_PYTHON_DOWNLOADS=never", "UV_LINK_MODE=copy", "UV_COMPILE_BYTECODE=1"):
        assert required in env_values, (
            f"dockerfile.base must set {required!r} in an ENV instruction "
            "(a token in an explanatory comment must not satisfy this)"
        )


@pytest.mark.unit
def test_docker_base_installs_exactly_once_before_essentia_and_checks_last() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    waf_idx = text.index("waf configure")
    after_waf = text[waf_idx:]
    assert re.search(r"uv export|uv pip sync|uv sync\b", after_waf) is None, (
        "dockerfile.base must not exact-sync again after the Essentia waf build"
    )

    last_run = text.rsplit("\nRUN ", 1)[-1]
    for expected in ("CUDAExecutionProvider", "essentia", "chromaprint", "sys.path"):
        assert expected in last_run, f"final RUN sanity check must assert {expected!r}"

    for probe in ("importlib.metadata", "version('onnxruntime-gpu')", "get_available_providers"):
        assert probe in last_run, (
            f"final RUN sanity check must exercise the C5 GPU metadata/provider contract with {probe!r}"
        )


@pytest.mark.unit
def test_app_dockerfile_adds_no_second_package_path() -> None:
    text = DOCKERFILE_APP.read_text(encoding="utf-8")
    assert "FROM ghcr.io/xiaden/nomarr-base:${BASE_TAG}" in text, (
        "app dockerfile must build on the pre-built base image"
    )
    for forbidden in ("pip install", "python -m venv", "RUN uv ", "uv sync", "uv pip"):
        assert forbidden not in text, f"app dockerfile must not install packages; found {forbidden!r}"
    for required in (
        "HEALTHCHECK",
        'ENTRYPOINT ["/usr/bin/tini", "--"]',
        "PYTHONPATH=/app:/usr/local/lib/python3/dist-packages",
        "USER 1000:1000",
        "EXPOSE 8356",
        'CMD ["python3", "-m", "nomarr.start"]',
    ):
        assert required in text, f"app dockerfile must preserve runtime contract {required!r}"


@pytest.mark.unit
def test_build_base_caller_grants_callee_permissions() -> None:
    caller = _load_yaml(DOCKER_PUBLISH)["jobs"]["build-base"].get("permissions") or {}
    callee = _load_yaml(BUILD_BASE)["jobs"]["build-base"]["permissions"]
    assert all(caller.get(k) == v for k, v in callee.items()), (
        "the build-base reusable-call job must grant every permission the callee requests, "
        f"at equal-or-greater level; caller={caller!r} callee={callee!r}"
    )


@pytest.mark.unit
def test_docker_publish_classifies_only_event_driven_release_aliases() -> None:
    workflow = _load_yaml(DOCKER_PUBLISH)
    on = _on(workflow)
    assert on["push"]["tags"] == ["v*"]
    dispatch = on["workflow_dispatch"]
    assert dispatch["inputs"]["channel"]["options"] == ["none", "preview", "develop"]

    run = next(step["run"] for step in workflow["jobs"]["policy"]["steps"] if step.get("id") == "policy")
    assert 'GITHUB_EVENT_NAME" == "push" && "$GITHUB_REF" == refs/tags/*' in run
    assert 'release_kind="stable"' in run
    assert 'release_kind="prerelease"' in run
    assert 'release_kind="manual"' in run
    assert "latest" in run
    assert "preview|develop" in run
    assert "github.ref_name" not in run, "manual aliases must not be inferred from the selected ref"


@pytest.mark.unit
def test_build_base_exposes_full_sha_output_and_publishes_it_on_all_arms() -> None:
    workflow = _load_yaml(BUILD_BASE)
    on = _on(workflow)
    assert on["workflow_call"]["outputs"]["base_tag"]["value"] == "${{ jobs.build-base.outputs.base_tag }}"
    assert on["workflow_call"]["inputs"]["publish_branch_aliases"]["default"] is False
    assert on["workflow_dispatch"]["inputs"]["publish_branch_aliases"]["default"] is True

    job = workflow["jobs"]["build-base"]
    tags_step = next(step for step in job["steps"] if step.get("id") == "tags")
    run = tags_step["run"]
    assert 'base_tag="sha-${GITHUB_SHA}"' in run
    assert 'tags=("${repo}:${base_tag}")' in run
    assert "base_tag=${base_tag}" in run


@pytest.mark.unit
def test_app_build_consumes_same_run_base_and_promote_ordering() -> None:
    jobs = _load_yaml(DOCKER_PUBLISH)["jobs"]
    build_job = jobs["build-and-push"]
    assert build_job["needs"] == ["policy", "build-base"], (
        f"build-and-push must run after the same-run base job; got {build_job.get('needs')!r}"
    )

    build_steps = [step for step in build_job["steps"] if step.get("uses", "").startswith("docker/build-push-action@")]
    assert len(build_steps) == 1, f"build-and-push must have exactly one build-push step; got {len(build_steps)}"
    build_args = build_steps[0]["with"].get("build-args", "")
    assert "BASE_TAG=${{ needs.build-base.outputs.base_tag }}" in build_args, (
        f"app build must consume the immutable same-run base tag; got {build_args!r}"
    )
    assert jobs["promote"]["needs"] == ["policy", "build-and-push"], (
        f"promote must depend on policy and build-and-push; got {jobs['promote'].get('needs')!r}"
    )


@pytest.mark.unit
def test_build_base_keeps_existing_branch_aliases_secondary_to_immutable_tag() -> None:
    job = _load_yaml(BUILD_BASE)["jobs"]["build-base"]
    tags_step = next(step for step in job["steps"] if step.get("id") == "tags")
    run = tags_step["run"]
    assert "latest" in run and "preview-base" in run and "v${base_version}" in run
    assert "inputs.publish_branch_aliases || false" in run
    assert 'tags+=("${repo}:preview-base")' not in run
    assert run.index('tags=("${repo}:${base_tag}")') < run.index("if [[")


@pytest.mark.unit
def test_docker_base_export_carries_exact_sync_flags() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    export_command = _dockerfile_run_command(text, "uv export")
    for flag in ("--no-emit-project", "--no-hashes"):
        assert flag in export_command, (
            f"dockerfile.base export command must carry {flag!r} (C5 exact-sync flags); "
            "scoped to the export RUN command so an explanatory comment cannot satisfy it"
        )
    assert "--python /usr/bin/python3" in export_command, (
        "the dockerfile.base export command must carry '--python /usr/bin/python3' "
        "(C5 exact-sync flags; forbids a managed CPython download per R11); scoped to the "
        "export RUN command so an explanatory comment cannot satisfy it"
    )


@pytest.mark.unit
def test_run_command_helper_scopes_assertions_to_run_bodies_only() -> None:
    """Regression: a token in a comment must never satisfy a RUN-scoped assertion.

    ``dockerfile.base`` carries the prose ``is REQUIRED`` in an explanatory
    comment. The helper must select only a ``RUN`` instruction body whose command
    starts with the prefix, so comment-only tokens are neither matched as
    prefixes nor smuggled into an isolated command.
    """
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        _dockerfile_run_command(text, "is REQUIRED")

    export_command = _dockerfile_run_command(text, "uv export")
    assert "is REQUIRED" not in export_command, (
        "the isolated uv export command must contain only the RUN body, not comment prose"
    )


@pytest.mark.unit
def test_docker_base_deletes_transient_requirements_in_export_run() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    rm_lines = [line for line in text.splitlines() if "rm -rf" in line]
    assert any("/tmp/nomarr-deps" in line and "/tmp/nomarr-gpu-requirements.txt" in line for line in rm_lines), (
        "dockerfile.base's export RUN must rm -rf both /tmp/nomarr-deps and "
        f"/tmp/nomarr-gpu-requirements.txt (R10: transient only); got {rm_lines!r}"
    )


@pytest.mark.unit
def test_docker_base_dry_run_precedes_real_exact_sync() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    dry_marker = "uv pip sync --system --break-system-packages --dry-run"
    real_marker = "uv pip sync --system --break-system-packages"

    dry_idx = text.find(dry_marker)
    assert dry_idx > 0, "dockerfile.base must dry-run the exact sync before applying it"
    real_idx = text.find(real_marker, dry_idx + len(dry_marker))
    assert real_idx != -1, "dockerfile.base must run the real exact sync after the dry-run"
    assert dry_idx < real_idx, (
        f"the R15 --dry-run evidence must precede the real exact sync (dry-run at {dry_idx}, real sync at {real_idx})"
    )


@pytest.mark.unit
def test_docker_publish_promote_job_retains_guard() -> None:
    promote = _load_yaml(DOCKER_PUBLISH)["jobs"]["promote"]
    assert promote["if"] == "needs.policy.outputs.aliases != ''", (
        f"promote must keep its non-empty promote_tags guard; got {promote.get('if')!r}"
    )


@pytest.mark.unit
def test_final_sanity_run_logs_resolved_module_files() -> None:
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    last_run = text.rsplit("\nRUN ", 1)[-1]
    for expected in ("essentia.__file__", "chromaprint.__file__"):
        assert expected in last_run, f"final RUN sanity check must log the resolved {expected!r} path (DD §8.2 / C5)"
    for probe in ("importlib.metadata", "version('onnxruntime-gpu')", "get_available_providers"):
        assert probe in last_run, (
            f"final RUN sanity check must exercise the C5 GPU metadata/provider contract with {probe!r}"
        )


@pytest.mark.unit
def test_docker_base_supplies_distutils_shim_to_essentia_waf() -> None:
    """Python 3.12 removed stdlib ``distutils``; Essentia's ``src/python/wscript``
    imports ``distutils.sysconfig`` at configure time.

    On Ubuntu noble the import shim is provided by ``python3-setuptools``. apt used
    to pull it in transitively as a hard dependency of ``python3-pip``, but uv
    installs only the lock contents, so ``setuptools`` must be an explicit
    build-only apt dependency: present while waf runs, purged afterwards.
    """
    text = DOCKERFILE_BASE.read_text(encoding="utf-8")
    install = _dockerfile_run_command(text, "apt-get update")
    purge = _dockerfile_run_command(text, "apt-get purge")

    assert "python3-setuptools" in install, (
        "dockerfile.base must apt-install python3-setuptools before the Essentia waf "
        "build (Python 3.12 has no stdlib distutils)"
    )
    assert "python3-setuptools" in purge, (
        "python3-setuptools is build-only and must be purged with the other "
        "build-only packages after the Essentia waf build"
    )
    assert text.index("python3-setuptools") < text.index("waf configure"), (
        "python3-setuptools must be installed before waf configure runs"
    )
