"""Tests for edit_file_replace_by_content tool."""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_replace_by_content import edit_file_replace_by_content


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Workspace root."""
    return tmp_path


def _make_file(ws: Path, rel: str, content: str) -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# -- Happy paths --


def test_replace_block_between_boundaries(ws: Path) -> None:
    """Replace a block identified by start and end boundary text."""
    content = textwrap.dedent("""\
        line 1
        # START
        old content
        # END
        line 5
    """)
    _make_file(ws, "f.py", content)

    result = edit_file_replace_by_content(
        file_path="f.py",
        start_boundary="# START",
        end_boundary="# END",
        expected_line_count=3,
        new_content="# START\nnew content\n# END\n",
        workspace_root=ws,
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1
    new_text = (ws / "f.py").read_text()
    assert "new content" in new_text
    assert "old content" not in new_text


def test_boundaries_are_inclusive(ws: Path) -> None:
    """Both start and end boundary lines are included in the replaced range."""
    content = "before\nBOUNDARY_A\nmiddle\nBOUNDARY_B\nafter\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_replace_by_content(
        file_path="f.txt",
        start_boundary="BOUNDARY_A",
        end_boundary="BOUNDARY_B",
        expected_line_count=3,
        new_content="REPLACED\n",
        workspace_root=ws,
    )

    assert result["status"] == "applied"
    new_text = (ws / "f.txt").read_text()
    assert "BOUNDARY_A" not in new_text
    assert "BOUNDARY_B" not in new_text
    assert "REPLACED" in new_text
    assert "before" in new_text
    assert "after" in new_text


def test_single_line_range(ws: Path) -> None:
    """Start and end boundary on the same line."""
    content = "aaa\nTARGET_LINE\nbbb\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_replace_by_content(
        file_path="f.txt",
        start_boundary="TARGET_LINE",
        end_boundary="TARGET_LINE",
        expected_line_count=1,
        new_content="REPLACED_LINE\n",
        workspace_root=ws,
    )

    assert result["status"] == "applied"
    assert (ws / "f.txt").read_text() == "aaa\nREPLACED_LINE\nbbb\n"


# -- Error cases --


def test_boundary_not_found(ws: Path) -> None:
    """Start boundary doesn't exist in file → error."""
    _make_file(ws, "f.txt", "some content\n")

    result = edit_file_replace_by_content(
        file_path="f.txt",
        start_boundary="DOES_NOT_EXIST",
        end_boundary="ALSO_MISSING",
        expected_line_count=1,
        new_content="x\n",
        workspace_root=ws,
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) > 0


def test_expected_line_count_mismatch(ws: Path) -> None:
    """Actual line count differs from expected → error."""
    content = "before\nSTART\nline a\nline b\nline c\nEND\nafter\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_replace_by_content(
        file_path="f.txt",
        start_boundary="START",
        end_boundary="END",
        expected_line_count=2,  # actual is 5 (START + 3 + END)
        new_content="replacement\n",
        workspace_root=ws,
    )

    assert result["status"] == "failed"
    # File untouched
    assert (ws / "f.txt").read_text() == content


def test_file_not_found(ws: Path) -> None:
    """File doesn't exist → error."""
    result = edit_file_replace_by_content(
        file_path="missing.py",
        start_boundary="x",
        end_boundary="y",
        expected_line_count=1,
        new_content="z\n",
        workspace_root=ws,
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) > 0


def test_no_change_returns_applied(ws: Path) -> None:
    """Replacing with identical content → applied status."""
    content = "aaa\nTARGET\nbbb\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_replace_by_content(
        file_path="f.txt",
        start_boundary="TARGET",
        end_boundary="TARGET",
        expected_line_count=1,
        new_content="TARGET\n",
        workspace_root=ws,
    )

    assert result["status"] == "applied"
    # File content should still contain TARGET
    assert "TARGET" in (ws / "f.txt").read_text()
