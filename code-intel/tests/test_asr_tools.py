"""Tests for ASR tools — asr_create, asr_read, asr_search."""

from pathlib import Path
from typing import Any

from mcp_code_intel.helpers.asr_md import parse_asr
from mcp_code_intel.tools.asr_create import asr_create
from mcp_code_intel.tools.asr_read import asr_read
from mcp_code_intel.tools.asr_search import asr_search

_DEFAULTS: dict[str, Any] = dict(
    priority=100,
    requirement=(
        "The system must respond to all API requests within 500ms at the 95th "
        "percentile under normal operating load."
    ),
)


def _create_sample(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    params: dict[str, Any] = {**_DEFAULTS, "workspace_root": tmp_path}
    params.update(kwargs)
    return asr_create(**params)


def test_asr_create_happy_path(tmp_path: Path) -> None:
    result = _create_sample(tmp_path)
    assert result["number"] == 1
    assert "path" in result
    assert (tmp_path / result["path"]).exists()
    assert (
        parse_asr((tmp_path / result["path"]).read_text()).requirement == _DEFAULTS["requirement"]
    )


def test_asr_create_empty_requirement(tmp_path: Path) -> None:
    result = _create_sample(tmp_path, requirement="")
    assert result["error"] == "invalid_requirement"


def test_asr_create_negative_priority(tmp_path: Path) -> None:
    result = _create_sample(tmp_path, priority=-1)
    assert result["error"] == "invalid_priority"


def test_asr_read_success(tmp_path: Path) -> None:
    _create_sample(tmp_path)
    result = asr_read(name="ASR-0001", workspace_root=tmp_path)
    assert result["number"] == 1
    assert result["priority"] == 100
    assert "requirement" in result
    assert "title" not in result
    assert "quality_attribute" not in result


def test_asr_read_name_variants(tmp_path: Path) -> None:
    _create_sample(tmp_path)
    for name in ("1", "0001", "ASR-0001", "ASR-0001.md"):
        result = asr_read(name=name, workspace_root=tmp_path)
        assert result.get("number") == 1, f"Failed for name={name!r}: {result}"


def test_asr_read_not_found(tmp_path: Path) -> None:
    result = asr_read(name="9999", workspace_root=tmp_path)
    assert result["error"] == "asr_not_found"


def test_asr_read_parse_error_on_old_format(tmp_path: Path) -> None:
    req_dir = tmp_path / "artifacts" / "requirements"
    req_dir.mkdir(parents=True, exist_ok=True)
    old_content = (
        "# ASR-001: Slow Search\n\n"
        "**Quality Attribute:** performance\n\n"
        "## Stimulus\n\nUser submits a search query.\n"
    )
    (req_dir / "ASR-0001.md").write_text(old_content, encoding="utf-8")
    result = asr_read(name="1", workspace_root=tmp_path)
    assert result["error"] == "parse_error"
    assert "path" in result


def test_asr_search_sorted_by_priority_ascending(tmp_path: Path) -> None:
    _create_sample(tmp_path, priority=200)
    _create_sample(tmp_path, priority=50)
    result = asr_search(workspace_root=tmp_path)
    assert len(result["results"]) == 2
    assert result["results"][0]["priority"] == 50


def test_asr_search_priority_min_max(tmp_path: Path) -> None:
    _create_sample(tmp_path, priority=50)
    _create_sample(tmp_path, priority=150)
    _create_sample(tmp_path, priority=300)
    result = asr_search(priority_min=100, priority_max=200, workspace_root=tmp_path)
    assert len(result["results"]) == 1
    assert result["results"][0]["priority"] == 150


def test_asr_search_status_filter(tmp_path: Path) -> None:
    _create_sample(tmp_path)
    r2 = _create_sample(tmp_path)
    asr_path = tmp_path / r2["path"]
    content = asr_path.read_text(encoding="utf-8")
    content = content.replace("**Status:** Active  ", "**Status:** Archived  ")
    asr_path.write_text(content, encoding="utf-8")
    result = asr_search(status="Archived", workspace_root=tmp_path)
    assert len(result["results"]) == 1


def test_asr_search_query_text(tmp_path: Path) -> None:
    _create_sample(tmp_path, requirement="The system must handle latency under load.")
    _create_sample(
        tmp_path,
        requirement="The system must be available 99.9% of the time.",
    )
    result = asr_search(query="latency", workspace_root=tmp_path)
    assert len(result["results"]) == 1


def test_asr_search_skips_old_format_file(tmp_path: Path) -> None:
    _create_sample(tmp_path)
    req_dir = tmp_path / "artifacts" / "requirements"
    old_content = (
        "# ASR-0099: Legacy Requirement\n\n"
        "**Quality Attribute:** performance\n\n"
        "## Stimulus\n\nUser action.\n"
    )
    (req_dir / "ASR-0099.md").write_text(old_content, encoding="utf-8")
    result = asr_search(workspace_root=tmp_path)
    assert result["total"] == 1
    assert "error" not in result


def test_asr_create_invalid_status(tmp_path: Path) -> None:
    result = _create_sample(tmp_path, status="Unknown")
    assert result["error"] == "invalid_status"


def test_asr_read_slug_format_returns_not_found(tmp_path: Path) -> None:
    result = asr_read(name="ASR-001-fast-search", workspace_root=tmp_path)
    assert result["error"] == "asr_not_found"


def test_asr_read_empty_name(tmp_path: Path) -> None:
    result = asr_read(name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_asr_search_no_requirements_directory(tmp_path: Path) -> None:
    result = asr_search(workspace_root=tmp_path)
    assert result == {"results": [], "total": 0}


def test_asr_create_already_exists(tmp_path: Path, monkeypatch: Any) -> None:
    req_dir = tmp_path / "artifacts" / "requirements"
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "ASR-0001.md").write_text("# Existing ASR\n", encoding="utf-8")

    import importlib

    asr_create_module = importlib.import_module("mcp_code_intel.tools.asr_create")
    monkeypatch.setattr(asr_create_module, "next_asr_number", lambda _requirements_dir: 1)

    result = _create_sample(tmp_path)
    assert result["error"] == "already_exists"


def test_asr_search_limit_truncates_results(tmp_path: Path) -> None:
    _create_sample(tmp_path, priority=100)
    _create_sample(tmp_path, priority=200)
    result = asr_search(limit=1, workspace_root=tmp_path)
    assert len(result["results"]) == 1
    assert result["total"] == 2
