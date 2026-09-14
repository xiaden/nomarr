"""Static gate for Plan E (uv sole-package-manager) config surfaces.

Static only: this test parses ``.github/dependabot.yml`` with
``yaml.safe_load`` and reads the two research-install text surfaces as text. It
never executes a package manager and never imports the research package.

Part 1 (binding contract C8) covers the Dependabot ``uv`` entry: a single
``uv`` root entry tracking ``develop``, patterns-only groups that all exclude
``onnxruntime*`` so the GPU ``<1.27`` cap is always a reviewed change (never
auto-batched), no stale ``tensorflow*`` pattern, no dead ``/code-intel`` entry,
and the untouched ``npm``/``github-actions``/``docker`` surfaces.

The intentionally RETAINED ``pip`` ``/`` entry is deliberately left unasserted:
asserting it absent would be wrong today, and asserting it present would block
its deferred verify-before-delete removal.

Part 2 (C8 / R17) proves the intentionally isolated research declaration/error
text instructs ``uv`` rather than pip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).parents[3]
DEPENDABOT = ROOT / ".github/dependabot.yml"
RESEARCH_REQUIREMENTS = ROOT / "scripts/embedding_research/requirements.txt"
RESEARCH_SCHEMA = ROOT / "scripts/embedding_research/db/_schema.py"

#: Canonical uv install command (C8) — must appear in both research install texts.
CANONICAL_UV_INSTALL = (
    "uv venv .venv-research && uv pip install --python .venv-research/bin/python "
    "-r /workspace/nomarr/scripts/embedding_research/requirements.txt"
)

_ONNXRUNTIME_EXCLUSION = "onnxruntime*"


# --- helpers ---------------------------------------------------------------


def _load_dependabot() -> dict[str, Any]:
    data = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{DEPENDABOT} did not parse as a mapping"
    entries = data.get("updates")
    assert isinstance(entries, list), f"{DEPENDABOT} must define an 'updates' list"
    return data


def _entries() -> list[dict[str, Any]]:
    return _load_dependabot()["updates"]


def _uv_entries() -> list[dict[str, Any]]:
    return [entry for entry in _entries() if entry.get("package-ecosystem") == "uv"]


def _groups(entry: dict[str, Any]) -> dict[str, Any]:
    groups = entry.get("groups") or {}
    assert isinstance(groups, dict), f"{DEPENDABOT}: groups must be a mapping; got {groups!r}"
    return groups


# --- Part 1: Dependabot uv entry & onnxruntime exclusion invariant (C8) ----


def test_uv_entry_is_single_root_entry_tracking_develop() -> None:
    uv_entries = _uv_entries()
    assert len(uv_entries) == 1, (
        f"{DEPENDABOT} must have exactly one package-ecosystem 'uv' entry; got {len(uv_entries)}"
    )
    uv = uv_entries[0]
    assert uv.get("directory") == "/", (
        f"{DEPENDABOT}: uv entry directory must be '/' (updates pyproject.toml + uv.lock); got {uv.get('directory')!r}"
    )
    assert uv.get("target-branch") == "develop", (
        f"{DEPENDABOT}: uv entry target-branch must be 'develop'; got {uv.get('target-branch')!r}"
    )


def test_every_uv_group_is_patterns_only_and_excludes_onnxruntime() -> None:
    """C8 safety invariant: the GPU onnxruntime cap is never auto-batched.

    Every group in the uv entry must declare non-empty ``patterns`` (patterns-only)
    and list ``onnxruntime*`` in ``exclude-patterns``. A single group that omits the
    exclusion would silently batch the GPU ``<1.27`` cap into an unreviewed update.
    """
    groups = _groups(_uv_entries()[0])
    assert groups, f"{DEPENDABOT}: uv entry must declare a non-empty groups mapping"

    for name, group in groups.items():
        assert isinstance(group, dict), f"{DEPENDABOT}: uv group {name!r} must be a mapping; got {group!r}"
        patterns = group.get("patterns")
        assert patterns, f"{DEPENDABOT}: uv group {name!r} must declare non-empty patterns (patterns-only)"
        excludes = group.get("exclude-patterns") or []
        assert _ONNXRUNTIME_EXCLUSION in excludes, (
            f"{DEPENDABOT}: uv group {name!r} must exclude {_ONNXRUNTIME_EXCLUSION!r} "
            f"(GPU onnxruntime cap must always be a reviewed change); got {excludes!r}"
        )


def test_no_group_patterns_reference_stale_tensorflow() -> None:
    offending = [
        f"{entry.get('package-ecosystem')}:{group_name}:{pattern!r}"
        for entry in _entries()
        for group_name, group in _groups(entry).items()
        for pattern in (group.get("patterns") or [])
        if "tensorflow" in pattern
    ]
    assert offending == [], f"{DEPENDABOT} must not retain the stale tensorflow* pattern(s): {offending}"


def test_no_dead_code_intel_directory_entry() -> None:
    offenders = [entry for entry in _entries() if entry.get("directory") == "/code-intel"]
    assert offenders == [], f"{DEPENDABOT} must not retain the dead pip /code-intel entry: {offenders!r}"


def test_npm_github_actions_and_docker_entries_retained() -> None:
    by_key = {(entry.get("package-ecosystem"), entry.get("directory")) for entry in _entries()}
    for surface in (("npm", "/frontend"), ("github-actions", "/"), ("docker", "/")):
        assert surface in by_key, f"{DEPENDABOT} must retain the untouched {surface[0]} entry at {surface[1]!r}"


# --- Part 2: research install text uses uv (C8 / R17) ----------------------


def test_research_requirements_header_uses_uv() -> None:
    text = RESEARCH_REQUIREMENTS.read_text(encoding="utf-8")
    assert "uv venv .venv-research" in text, f"{RESEARCH_REQUIREMENTS} header must instruct 'uv venv .venv-research'"
    assert "uv pip install --python .venv-research/bin/python" in text, (
        f"{RESEARCH_REQUIREMENTS} header must instruct 'uv pip install --python .venv-research/bin/python'"
    )
    assert "python -m pip" not in text, f"{RESEARCH_REQUIREMENTS} must not instruct 'python -m pip'"


def test_research_schema_install_messages_use_uv() -> None:
    text = RESEARCH_SCHEMA.read_text(encoding="utf-8")
    occurrences = text.count(CANONICAL_UV_INSTALL)
    assert occurrences >= 2, (
        f"{RESEARCH_SCHEMA} must contain the canonical uv install command in both the "
        f"_require_duckdb and require_supported_duckdb install messages; found {occurrences}"
    )
    assert "python -m pip" not in text, f"{RESEARCH_SCHEMA} must not instruct 'python -m pip'"
