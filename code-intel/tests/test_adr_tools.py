"""Tests for ADR tools — adr_create, adr_read, adr_search.

Covers:
- adr_create: happy path, auto-numbering, invalid status/title/tags, source_log validation, parseable
- adr_read: by number/filename/prefix, not found, path traversal, empty name
- adr_search: no filters, by tag, by status, by query, combined, limit, empty dir, sort order
"""

from pathlib import Path

from mcp_code_intel.helpers.adr_md import parse_adr
from mcp_code_intel.tools.adr_create import adr_create
from mcp_code_intel.tools.adr_read import adr_read
from mcp_code_intel.tools.adr_search import adr_search

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sample_adr(tmp_path: Path, **kwargs) -> dict:
    defaults = dict(
        title="Use Edges",
        status="Proposed",
        tags=["persistence"],
        context="We need edges.",
        decision="Use them.",
        consequences="Faster queries.",
        workspace_root=tmp_path,
    )
    defaults.update(kwargs)
    return adr_create(**defaults)


# ---------------------------------------------------------------------------
# adr_create
# ---------------------------------------------------------------------------


def test_adr_create_happy_path(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path)
    assert "path" in result
    assert result["number"] == 1
    assert result["title"] == "Use Edges"
    created = tmp_path / result["path"]
    assert created.exists()


def test_adr_create_file_is_parseable(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path)
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    adr = parse_adr(md)
    assert adr.title == "Use Edges"
    assert adr.status == "Proposed"
    assert adr.tags == ["persistence"]


def test_adr_create_auto_numbering(tmp_path: Path) -> None:
    _create_sample_adr(tmp_path, title="First")
    result = _create_sample_adr(tmp_path, title="Second")
    assert result["number"] == 2


def test_adr_create_invalid_status(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, status="Invalid")
    assert result["error"] == "invalid_status"


def test_adr_create_empty_title(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, title="")
    assert result["error"] == "invalid_title"


def test_adr_create_no_tags(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, tags=[])
    assert result["error"] == "invalid_tags"


def test_adr_create_empty_context(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, context="")
    assert result["error"] == "invalid_section"


def test_adr_create_empty_decision(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, decision="")
    assert result["error"] == "invalid_section"


def test_adr_create_empty_consequences(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, consequences="")
    assert result["error"] == "invalid_section"


def test_adr_create_invalid_source_log(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, source_log="bad-format")
    assert result["error"] == "invalid_source_log"


def test_adr_create_valid_source_log(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, source_log="rnd-test#L10")
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    adr = parse_adr(md)
    assert adr.source_log == "rnd-test#L10"


def test_adr_create_extra_sections(tmp_path: Path) -> None:
    result = _create_sample_adr(
        tmp_path,
        extra_sections=[{"heading": "Migration", "content": "Migration notes."}],
    )
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## Migration" in md


def test_adr_create_with_references(tmp_path: Path) -> None:
    result = _create_sample_adr(tmp_path, references="- [Link](url)")
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## References" in md


# ---------------------------------------------------------------------------
# adr_read
# ---------------------------------------------------------------------------


def test_adr_read_by_number(tmp_path: Path) -> None:
    _create_sample_adr(tmp_path)
    result = adr_read(name="1", workspace_root=tmp_path)
    assert result["title"] == "Use Edges"
    assert result["number"] == 1


def test_adr_read_by_padded_number(tmp_path: Path) -> None:
    _create_sample_adr(tmp_path)
    result = adr_read(name="001", workspace_root=tmp_path)
    assert result["title"] == "Use Edges"


def test_adr_read_by_filename(tmp_path: Path) -> None:
    result1 = _create_sample_adr(tmp_path)
    filename = result1["path"].split("/")[-1]
    result = adr_read(name=filename, workspace_root=tmp_path)
    assert result["title"] == "Use Edges"


def test_adr_read_not_found(tmp_path: Path) -> None:
    result = adr_read(name="999", workspace_root=tmp_path)
    assert result["error"] == "adr_not_found"


def test_adr_read_empty_name(tmp_path: Path) -> None:
    result = adr_read(name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_adr_read_path_traversal_rejected(tmp_path: Path) -> None:
    result = adr_read(name="../../../etc/passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_adr_read_backslash_rejected(tmp_path: Path) -> None:
    result = adr_read(name="..\\etc\\passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


# ---------------------------------------------------------------------------
# adr_search
# ---------------------------------------------------------------------------


def _setup_search_fixtures(tmp_path: Path) -> None:
    """Create 3 ADRs for search testing."""
    _create_sample_adr(tmp_path, title="Use Edges", tags=["persistence", "arangodb"], status="Proposed")
    _create_sample_adr(tmp_path, title="Adopt ONNX", tags=["ml", "inference"], status="Accepted")
    _create_sample_adr(tmp_path, title="REST API Design", tags=["api", "persistence"], status="Proposed")


def test_adr_search_no_filters(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(workspace_root=tmp_path)
    assert result["total"] == 3
    assert len(result["results"]) == 3


def test_adr_search_by_tag(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="persistence", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_by_status(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(status="Accepted", workspace_root=tmp_path)
    assert result["total"] == 1
    assert result["results"][0]["title"] == "Adopt ONNX"


def test_adr_search_by_query(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(query="ONNX", workspace_root=tmp_path)
    assert result["total"] == 1


def test_adr_search_combined_filters(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="persistence", status="Proposed", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_limit(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(limit=1, workspace_root=tmp_path)
    assert len(result["results"]) == 1
    assert result["total"] == 3


def test_adr_search_empty_dir(tmp_path: Path) -> None:
    result = adr_search(workspace_root=tmp_path)
    assert result["results"] == []
    assert result["total"] == 0


def test_adr_search_sort_order_newest_first(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(workspace_root=tmp_path)
    numbers = [r["number"] for r in result["results"]]
    assert numbers == sorted(numbers, reverse=True)


def test_adr_search_tag_case_insensitive(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(tag="PERSISTENCE", workspace_root=tmp_path)
    assert result["total"] == 2


def test_adr_search_query_case_insensitive(tmp_path: Path) -> None:
    _setup_search_fixtures(tmp_path)
    result = adr_search(query="onnx", workspace_root=tmp_path)
    assert result["total"] == 1
