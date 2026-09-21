"""Static trigger-topology gates for container publication."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[3]
BUILD_BASE = ROOT / ".github/workflows/build-base.yml"
DOCKER_PUBLISH = ROOT / ".github/workflows/docker-publish.yml"
BASE_VERSION_BUMP = ROOT / ".github/workflows/base-version-bump.yml"

BASE_ONLY_PATHS = {
    "dockerfile.base",
    "build_resources/essentia/**",
    "build_resources/scripts/**",
}
DEPENDENCY_INPUTS = {
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "BASE_VERSION",
}


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} did not parse as a mapping"
    return data


def _on(workflow: dict) -> dict:
    """Return the ``on:`` mapping (PyYAML 1.1 may parse ``on`` as ``True``)."""
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict), f"workflow 'on' must be a mapping, got {on!r}"
    return on


@pytest.mark.unit
def test_docker_publish_is_release_tag_triggered_with_explicit_manual_channels() -> None:
    on = _on(_load_yaml(DOCKER_PUBLISH))
    assert on["push"] == {"tags": ["v*"]}
    assert on["workflow_dispatch"]["inputs"]["channel"]["options"] == ["none", "preview", "develop"]
    assert on["workflow_dispatch"]["inputs"]["channel"]["default"] == "none"


@pytest.mark.unit
def test_e2e_defaults_to_full_sha_image_tag() -> None:
    workflow = _load_yaml(ROOT / ".github/workflows/e2e.yml")
    dispatch = _on(workflow)["workflow_dispatch"]
    image_tag = dispatch["inputs"]["image_tag"]
    assert "sha-<full-commit-sha>" in image_tag["description"]
    run = next(step["run"] for step in workflow["jobs"]["e2e"]["steps"] if step.get("id") == "image")
    assert 'TAG="${{ inputs.image_tag }}"' in run
    assert 'TAG="sha-${{ github.sha }}"' in run
    assert 'TAG="${SHA:0:7}"' not in run


@pytest.mark.unit
def test_release_policy_uses_latest_exact_name_check_run() -> None:
    workflow = _load_yaml(DOCKER_PUBLISH)
    run = next(
        step["run"]
        for step in workflow["jobs"]["policy"]["steps"]
        if step.get("name") == "Require successful CI for automatic release"
    )
    assert ".check_runs[] | select(.name == $name)" in run
    assert 'sort_by([(.created_at // ""), (.id // 0)])' in run
    assert '"pending"' in run
    assert '"failure"' in run
    assert "any(.[]" not in run


@pytest.mark.unit
def test_build_base_declares_workflow_call_and_dispatch_only() -> None:
    on = _on(_load_yaml(BUILD_BASE))
    assert {"workflow_call", "workflow_dispatch"} <= set(on), (
        f"build-base.yml must declare workflow_call + workflow_dispatch; got {sorted(on)!r}"
    )
    assert "push" not in on, (
        "build-base.yml must not carry a standalone push trigger; docker-publish.yml is the "
        f"single push-triggered base orchestrator; got push={on.get('push')!r}"
    )


@pytest.mark.unit
def test_base_version_bump_push_paths_stay_base_only() -> None:
    on = _on(_load_yaml(BASE_VERSION_BUMP))
    paths = set(on["push"]["paths"])
    assert paths == BASE_ONLY_PATHS, (
        f"base-version-bump.yml push paths must remain exactly the base-only inputs; got {sorted(paths)!r}"
    )
    assert not (paths & DEPENDENCY_INPUTS), (
        "base-version-bump.yml must not list any dependency input (no self-retrigger); "
        f"got {sorted(paths & DEPENDENCY_INPUTS)!r}"
    )
