"""Tests for DD tools — dd_create, dd_read, dd_archive.

Covers:
- dd_create: happy path, invalid slug/status/title, duplicate, extra sections, parseable output
- dd_read: by slug/filename/prefix, pending vs completed, not found, empty name
- dd_archive: happy path, pending plans block, not found, status→Completed, path traversal
"""

from pathlib import Path

from mcp_code_intel.helpers.dd_md import DESIGNS_COMPLETED_DIR, DESIGNS_PENDING_DIR, parse_dd
from mcp_code_intel.tools.dd_archive import dd_archive
from mcp_code_intel.tools.dd_create import dd_create
from mcp_code_intel.tools.dd_read import dd_read

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sample_dd(
    tmp_path: Path,
    slug: str = "my-feature",
    title: str = "My Feature",
    status: str = "Draft",
    author: str = "test-agent",
    scope: str = "Test scope",
    problem_statement: str = "Test problem",
    architecture: str = "Test architecture",
    design_goals: str = "",
    constraints: str = "",
    open_questions: str = "",
    related_documents: list[dict[str, str]] | None = None,
    extra_sections: list[dict[str, str]] | None = None,
) -> dict:
    return dd_create(
        title=title,
        slug=slug,
        status=status,
        author=author,
        scope=scope,
        problem_statement=problem_statement,
        architecture=architecture,
        design_goals=design_goals,
        constraints=constraints,
        open_questions=open_questions,
        related_documents=related_documents,
        extra_sections=extra_sections,
        workspace_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# dd_create
# ---------------------------------------------------------------------------


def test_dd_create_happy_path(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path)
    assert "path" in result
    assert result["title"] == "My Feature"
    created = tmp_path / result["path"]
    assert created.exists()


def test_dd_create_file_is_parseable(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path)
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    doc = parse_dd(md)
    assert doc.title == "My Feature"
    assert doc.status == "Draft"


def test_dd_create_invalid_slug(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path, slug="Bad Slug!")
    assert result["error"] == "invalid_slug"


def test_dd_create_invalid_status(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path, status="Invalid")
    assert result["error"] == "invalid_status"


def test_dd_create_empty_title(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path, title="")
    assert result["error"] == "invalid_title"


def test_dd_create_whitespace_title(tmp_path: Path) -> None:
    result = _create_sample_dd(tmp_path, title="   ")
    assert result["error"] == "invalid_title"


def test_dd_create_duplicate_rejected(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="duplicate")
    result = _create_sample_dd(tmp_path, slug="duplicate")
    assert result["error"] == "already_exists"


def test_dd_create_extra_sections(tmp_path: Path) -> None:
    result = _create_sample_dd(
        tmp_path,
        slug="extra-sec",
        extra_sections=[{"heading": "Custom", "content": "Custom content."}],
    )
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## Custom" in md
    assert "Custom content." in md


def test_dd_create_optional_sections(tmp_path: Path) -> None:
    result = _create_sample_dd(
        tmp_path,
        slug="all-opts",
        design_goals="Goals here.",
        constraints="Constraints here.",
        open_questions="Questions here.",
    )
    assert "path" in result
    md = (tmp_path / result["path"]).read_text(encoding="utf-8")
    doc = parse_dd(md)
    assert "Design Goals" in doc.sections
    assert "Constraints" in doc.sections
    assert "Open Questions" in doc.sections


# ---------------------------------------------------------------------------
# dd_read
# ---------------------------------------------------------------------------


def test_dd_read_by_slug(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="read-test")
    result = dd_read(name="read-test", workspace_root=tmp_path)
    assert result["title"] == "My Feature"
    assert result["location"] == "pending"


def test_dd_read_by_filename(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="by-file")
    result = dd_read(name="DD-by-file.md", workspace_root=tmp_path)
    assert result["title"] == "My Feature"


def test_dd_read_by_prefix(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="by-prefix")
    result = dd_read(name="DD-by-prefix", workspace_root=tmp_path)
    assert result["title"] == "My Feature"


def test_dd_read_completed(tmp_path: Path) -> None:
    """DD in completed dir is findable."""
    completed_dir = tmp_path / DESIGNS_COMPLETED_DIR
    completed_dir.mkdir(parents=True)
    (completed_dir / "DD-old-feature.md").write_text(
        "# Old Feature — Design Document\n\n"
        "**Status:** Completed  \n"
        "**Author:** test  \n"
        "**Created:** 2026-01-01  \n\n"
        "---\n\n## Scope\n\nContent.\n",
        encoding="utf-8",
    )
    result = dd_read(name="old-feature", workspace_root=tmp_path)
    assert result["title"] == "Old Feature"
    assert result["location"] == "completed"


def test_dd_read_not_found(tmp_path: Path) -> None:
    result = dd_read(name="nonexistent", workspace_root=tmp_path)
    assert result["error"] == "dd_not_found"


def test_dd_read_empty_name(tmp_path: Path) -> None:
    result = dd_read(name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_dd_read_path_traversal_rejected(tmp_path: Path) -> None:
    result = dd_read(name="../../../etc/passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"
    assert "path separators" in result["message"]


def test_dd_read_backslash_rejected(tmp_path: Path) -> None:
    result = dd_read(name="..\\secret", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


# ---------------------------------------------------------------------------
# dd_archive
# ---------------------------------------------------------------------------


def test_dd_archive_happy_path(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="archivable")
    result = dd_archive(name="archivable", workspace_root=tmp_path)
    assert result["archived"] is True
    assert DESIGNS_COMPLETED_DIR in result["path"]
    # Source should be gone
    assert not (tmp_path / DESIGNS_PENDING_DIR / "DD-archivable.md").exists()
    # Dest should exist
    assert (tmp_path / DESIGNS_COMPLETED_DIR / "DD-archivable.md").exists()


def test_dd_archive_status_updated_to_completed(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="status-chk")
    dd_archive(name="status-chk", workspace_root=tmp_path)
    md = (tmp_path / DESIGNS_COMPLETED_DIR / "DD-status-chk.md").read_text(encoding="utf-8")
    doc = parse_dd(md)
    assert doc.status == "Completed"


def test_dd_archive_status_rewrite_from_approved(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="from-approved", status="Approved")
    dd_archive(name="from-approved", workspace_root=tmp_path)
    md = (tmp_path / DESIGNS_COMPLETED_DIR / "DD-from-approved.md").read_text(encoding="utf-8")
    doc = parse_dd(md)
    assert doc.status == "Completed"


def test_dd_archive_pending_plans_block(tmp_path: Path) -> None:
    _create_sample_dd(tmp_path, slug="blocked")
    plans_dir = tmp_path / "artifacts/plans/pending"
    plans_dir.mkdir(parents=True)
    (plans_dir / "TASK-blocked-A-first.md").write_text("x")
    result = dd_archive(name="blocked", workspace_root=tmp_path)
    assert result["error"] == "pending_plans"


def test_dd_archive_not_found(tmp_path: Path) -> None:
    result = dd_archive(name="missing", workspace_root=tmp_path)
    assert result["error"] == "not_found"


def test_dd_archive_path_traversal_rejected(tmp_path: Path) -> None:
    result = dd_archive(name="../../../etc/passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_dd_archive_empty_name(tmp_path: Path) -> None:
    result = dd_archive(name="", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"


def test_dd_archive_with_backslash_rejected(tmp_path: Path) -> None:
    result = dd_archive(name="..\\etc\\passwd", workspace_root=tmp_path)
    assert result["error"] == "invalid_name"
