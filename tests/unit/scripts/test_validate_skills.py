"""Tests for scripts/human-scripts/validate_skills.py.

These tests pin the validator's Phase-1 contract: it scans the *active* project
skill directory ``.opencode/skills`` — never the obsolete ``.github/skills``
mirror tree — while preserving its CLI behavior (text/JSON output, optional
specific-skill argument, ``--check-refs``, repo-root derivation, and the
exit-code contract).

Every test runs against a temporary repository that contains ``.opencode/skills``
and no ``.github/skills``, so they are independent of the live ~40-skill audited
inventory and never require ``.github/skills`` to exist.

The module is loaded by on-disk path (``scripts/human-scripts`` is not importable
as a dotted package because of the hyphen), following the same pattern as
``test_api_coverage_roots.py``. Loading the module performs no writes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# <repo>/tests/unit/scripts -> <repo> (same derivation as ./conftest.py).
REPO_ROOT = Path(__file__).resolve().parents[3]
VALIDATE_SKILLS = REPO_ROOT / "scripts/human-scripts/validate_skills.py"

FRONTMATTER = """---
name: {name}
description: Use when {name} is needed. Provides guidance.
---
"""

BODY = """

# {name}

Instructions for {name}.
"""


def _load_module(name: str, path: Path):
    """Load a module from its on-disk path, returning the module object.

    The module is registered in ``sys.modules`` before execution because
    validate_skills.py uses a top-level ``@dataclass`` whose ``__module__``
    must resolve for the decorator to process the class.
    """
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validator():
    """The validate_skills module loaded from its on-disk path."""
    return _load_module("validate_skills", VALIDATE_SKILLS)


def _write_skill(repo: Path, skill_name: str, *, body: str = "") -> Path:
    """Create ``.opencode/skills/<skill_name>/SKILL.md`` in a temp repo."""
    skill_dir = repo / ".opencode" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = FRONTMATTER.format(name=skill_name) + body + BODY.format(name=skill_name)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_dir


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """A minimal repository with ``.opencode/skills`` and no ``.github/skills``."""
    (tmp_path / ".opencode" / "skills").mkdir(parents=True)
    # Assert the fixture precondition: no .github/skills mirror tree exists.
    assert not (tmp_path / ".github" / "skills").exists()
    return tmp_path


@pytest.mark.unit
class TestActiveDirectoryDiscovery:
    def test_find_all_skills_discovers_opencode_only(self, validator, tmp_repo: Path) -> None:
        _write_skill(tmp_repo, "alpha-skill")
        _write_skill(tmp_repo, "beta-skill")

        found = validator.find_all_skills(tmp_repo)

        names = sorted(p.name for p in found)
        assert names == ["alpha-skill", "beta-skill"]
        # Every discovered skill must live under .opencode/skills.
        for p in found:
            assert p.relative_to(tmp_repo / ".opencode" / "skills")

    def test_no_github_skills_is_not_an_error(self, validator, tmp_repo: Path) -> None:
        # A repo with .opencode/skills but NO .github/skills must discover the
        # active skills and not fail merely because the mirror tree is absent.
        _write_skill(tmp_repo, "only-skill")

        found = validator.find_all_skills(tmp_repo)

        assert [p.name for p in found] == ["only-skill"]

    def test_github_skills_mirror_is_not_treated_as_active(self, validator, tmp_repo: Path) -> None:
        # Even if a stale .github/skills mirror exists, it must never be returned
        # as an active skill — the validator owns .opencode/skills only.
        _write_skill(tmp_repo, "active-skill")
        _write_skill(tmp_repo, "active-skill-two")
        stale_mirror = tmp_repo / ".github" / "skills" / "stale-mirror"
        stale_mirror.mkdir(parents=True)
        (stale_mirror / "SKILL.md").write_text(FRONTMATTER.format(name="stale-mirror"), encoding="utf-8")

        found = validator.find_all_skills(tmp_repo)

        names = [p.name for p in found]
        assert "active-skill" in names and "active-skill-two" in names
        assert "stale-mirror" not in names
        for p in found:
            assert ".opencode" in p.parts


@pytest.mark.unit
class TestFrontmatterAndNameValidation:
    def test_valid_skill_passes(self, validator, tmp_repo: Path) -> None:
        skill_dir = _write_skill(tmp_repo, "good-skill")

        result = validator.validate_skill(skill_dir, tmp_repo)

        assert result.valid is True
        assert result.errors == []

    def test_name_mismatch_is_error(self, validator, tmp_repo: Path) -> None:
        skill_dir = _write_skill(tmp_repo, "actual-dir")
        # Overwrite with a frontmatter whose name disagrees with the directory.
        content = FRONTMATTER.format(name="wrong-name") + BODY.format(name="wrong-name")
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

        result = validator.validate_skill(skill_dir, tmp_repo)

        assert result.valid is False
        assert any("does not match directory" in e for e in result.errors)

    def test_missing_skill_file_is_error(self, validator, tmp_repo: Path) -> None:
        empty_dir = tmp_repo / ".opencode" / "skills" / "empty-skill"
        empty_dir.mkdir(parents=True)

        result = validator.validate_skill(empty_dir, tmp_repo)

        assert result.valid is False
        assert any("Missing SKILL.md" in e for e in result.errors)


@pytest.mark.unit
class TestCheckRefs:
    def test_missing_reference_is_flagged(self, validator, tmp_repo: Path) -> None:
        # A code reference under the temp repo root that does not exist.
        skill_dir = _write_skill(
            tmp_repo,
            "ref-skill",
            body="\nSee `nomarr/components/missing.py` for details.\n",
        )

        result = validator.validate_skill(skill_dir, tmp_repo, check_refs=True)

        assert result.valid is False
        assert any("nomarr/components/missing.py" in r for r in result.invalid_refs)

    def test_existing_reference_is_clean(self, validator, tmp_repo: Path) -> None:
        existing = tmp_repo / "nomarr" / "components" / "present.py"
        existing.parent.mkdir(parents=True)
        existing.write_text("", encoding="utf-8")
        skill_dir = _write_skill(
            tmp_repo,
            "ref-skill",
            body="\nSee `nomarr/components/present.py` for details.\n",
        )

        result = validator.validate_skill(skill_dir, tmp_repo, check_refs=True)

        assert result.valid is True
        assert result.invalid_refs == []


@pytest.mark.unit
class TestCliContract:
    """Exercise main() against a temp repo by pointing its __file__-derived root
    at the temp tree. Repo root is computed as three ``.parent`` hops from the
    script location (scripts/human-scripts/validate_skills.py), so a fake script
    path under ``<tmp>/scripts/human-scripts/`` makes main resolve to <tmp>.
    main() reads args from sys.argv, so that is patched too."""

    def _run(self, monkeypatch, validator, tmp_repo: Path, argv: list[str]) -> int:
        import sys

        fake_script = tmp_repo / "scripts" / "human-scripts" / "validate_skills.py"
        monkeypatch.setattr(validator, "__file__", str(fake_script))
        monkeypatch.setattr(sys, "argv", [str(fake_script), *argv])
        return validator.main()

    def test_all_valid_returns_zero_text(self, validator, monkeypatch, tmp_repo: Path, capsys) -> None:
        _write_skill(tmp_repo, "alpha-skill")
        _write_skill(tmp_repo, "beta-skill")

        code = self._run(monkeypatch, validator, tmp_repo, [])

        out = capsys.readouterr().out
        assert code == 0
        assert "2/2 passed" in out

    def test_json_output_reports_opencode_only(self, validator, monkeypatch, tmp_repo: Path, capsys) -> None:
        _write_skill(tmp_repo, "alpha-skill")
        _write_skill(tmp_repo, "beta-skill")

        code = self._run(monkeypatch, validator, tmp_repo, ["--format=json"])

        payload = json.loads(capsys.readouterr().out)
        assert code == 0
        assert payload["summary"]["total"] == 2
        assert payload["summary"]["failed"] == 0

    def test_specific_skill_selection(self, validator, monkeypatch, tmp_repo: Path, capsys) -> None:
        # Only alpha-skill is valid; beta-skill has a name mismatch. Selecting
        # alpha-skill specifically must pass even though beta-skill is broken.
        _write_skill(tmp_repo, "alpha-skill")
        beta_dir = _write_skill(tmp_repo, "beta-skill")
        (beta_dir / "SKILL.md").write_text(
            FRONTMATTER.format(name="wrong-name") + BODY.format(name="wrong-name"),
            encoding="utf-8",
        )

        code = self._run(monkeypatch, validator, tmp_repo, ["alpha-skill"])

        out = capsys.readouterr().out
        assert code == 0
        assert "1/1 passed" in out
        assert "beta-skill" not in out

    def test_unknown_skill_returns_error(self, validator, monkeypatch, tmp_repo: Path, capsys) -> None:
        code = self._run(monkeypatch, validator, tmp_repo, ["ghost-skill"])

        captured = capsys.readouterr()
        assert code == 1
        assert "not found" in captured.err

    def test_invalid_skill_returns_nonzero(self, validator, monkeypatch, tmp_repo: Path, capsys) -> None:
        skill_dir = _write_skill(tmp_repo, "broken-skill")
        (skill_dir / "SKILL.md").write_text(
            FRONTMATTER.format(name="wrong-name") + BODY.format(name="wrong-name"),
            encoding="utf-8",
        )

        code = self._run(monkeypatch, validator, tmp_repo, [])

        out = capsys.readouterr().out
        assert code == 1
        assert "0/1 passed" in out
