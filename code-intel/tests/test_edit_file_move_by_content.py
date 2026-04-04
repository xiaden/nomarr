"""Tests for edit_file_move_by_content tool."""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_move_by_content import edit_file_move_by_content


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Workspace root."""
    return tmp_path


def _make_file(ws: Path, rel: str, content: str) -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# -- Same-file move --


def test_same_file_move_after_anchor(ws: Path) -> None:
    """Move a block after a target anchor within the same file."""
    content = textwrap.dedent("""\
        line A
        # MOVE_START
        moved content
        # MOVE_END
        line B
        # TARGET
        line C
    """)
    _make_file(ws, "f.py", content)

    result = edit_file_move_by_content(
        file_path="f.py",
        start_boundary="# MOVE_START",
        end_boundary="# MOVE_END",
        expected_line_count=3,
        target_anchor="# TARGET",
        target_position="after",
        workspace_root=ws,
    )

    assert result["changed"] is True
    assert result["lines_moved"] == 3
    new_text = (ws / "f.py").read_text()
    # Content should appear after TARGET, not before line B
    lines = new_text.splitlines()
    target_idx = next(i for i, l in enumerate(lines) if "# TARGET" in l)
    assert "# MOVE_START" in lines[target_idx + 1]


def test_same_file_move_before_anchor(ws: Path) -> None:
    """Move a block before a target anchor within the same file."""
    content = textwrap.dedent("""\
        # TARGET
        line A
        line B
        # MOVE_START
        moved content
        # MOVE_END
    """)
    _make_file(ws, "f.py", content)

    result = edit_file_move_by_content(
        file_path="f.py",
        start_boundary="# MOVE_START",
        end_boundary="# MOVE_END",
        expected_line_count=3,
        target_anchor="# TARGET",
        target_position="before",
        workspace_root=ws,
    )

    assert result["changed"] is True
    new_text = (ws / "f.py").read_text()
    lines = new_text.splitlines()
    target_idx = next(i for i, l in enumerate(lines) if "# TARGET" in l)
    # Moved block should be just before TARGET
    assert "# MOVE_END" in lines[target_idx - 1]


def test_same_file_noop_target_in_source(ws: Path) -> None:
    """Target within source range → no change."""
    content = "before\n# START\nmiddle\n# END\nafter\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_move_by_content(
        file_path="f.txt",
        start_boundary="# START",
        end_boundary="# END",
        expected_line_count=3,
        target_anchor="middle",
        target_position="after",
        workspace_root=ws,
    )

    assert result["changed"] is False


# -- Cross-file move --


def test_cross_file_move(ws: Path) -> None:
    """Move content from one file to another."""
    src_content = textwrap.dedent("""\
        keep 1
        # MOVE_START
        moved line
        # MOVE_END
        keep 2
    """)
    tgt_content = textwrap.dedent("""\
        target line 1
        # ANCHOR
        target line 2
    """)
    _make_file(ws, "src.py", src_content)
    _make_file(ws, "tgt.py", tgt_content)

    result = edit_file_move_by_content(
        file_path="src.py",
        start_boundary="# MOVE_START",
        end_boundary="# MOVE_END",
        expected_line_count=3,
        target_anchor="# ANCHOR",
        target_position="after",
        workspace_root=ws,
        target_file="tgt.py",
    )

    assert result["changed"] is True
    assert result["lines_moved"] == 3
    # Source should not contain moved content
    src_new = (ws / "src.py").read_text()
    assert "moved line" not in src_new
    assert "keep 1" in src_new
    assert "keep 2" in src_new
    # Target should contain moved content
    tgt_new = (ws / "tgt.py").read_text()
    assert "moved line" in tgt_new


def test_new_file_move(ws: Path) -> None:
    """Move content into a brand-new file (no anchor)."""
    src_content = textwrap.dedent("""\
        keep
        # EXTRACT_START
        extracted line
        # EXTRACT_END
        also keep
    """)
    _make_file(ws, "src.py", src_content)

    result = edit_file_move_by_content(
        file_path="src.py",
        start_boundary="# EXTRACT_START",
        end_boundary="# EXTRACT_END",
        expected_line_count=3,
        target_anchor=None,
        target_position="after",
        workspace_root=ws,
        target_file="new_file.py",
    )

    assert result["changed"] is True
    assert result.get("created_new_file") is True
    # Source should not contain extracted content
    src_new = (ws / "src.py").read_text()
    assert "extracted line" not in src_new
    # New file should contain extracted content
    new_text = (ws / "new_file.py").read_text()
    assert "extracted line" in new_text


# -- Error cases --


def test_source_boundary_not_found(ws: Path) -> None:
    """Source boundaries don't match → error."""
    _make_file(ws, "f.txt", "some content\n")

    result = edit_file_move_by_content(
        file_path="f.txt",
        start_boundary="NONEXISTENT",
        end_boundary="ALSO_MISSING",
        expected_line_count=1,
        target_anchor="some",
        target_position="after",
        workspace_root=ws,
    )

    assert "error" in result
    assert result["changed"] is False


def test_target_anchor_not_found(ws: Path) -> None:
    """Target anchor doesn't match → error."""
    content = "# START\ncontent\n# END\n"
    _make_file(ws, "f.txt", content)

    result = edit_file_move_by_content(
        file_path="f.txt",
        start_boundary="# START",
        end_boundary="# END",
        expected_line_count=3,
        target_anchor="NONEXISTENT_ANCHOR",
        target_position="after",
        workspace_root=ws,
    )

    assert "error" in result
    assert result["changed"] is False


def test_no_anchor_same_file_error(ws: Path) -> None:
    """target_anchor=None without target_file → error."""
    _make_file(ws, "f.txt", "# START\nline\n# END\n")

    result = edit_file_move_by_content(
        file_path="f.txt",
        start_boundary="# START",
        end_boundary="# END",
        expected_line_count=3,
        target_anchor=None,
        target_position="after",
        workspace_root=ws,
    )

    assert "error" in result
    assert result["changed"] is False


def test_new_file_already_exists_error(ws: Path) -> None:
    """target_file already exists when target_anchor=None → error."""
    _make_file(ws, "src.py", "# START\nline\n# END\n")
    _make_file(ws, "existing.py", "already here\n")

    result = edit_file_move_by_content(
        file_path="src.py",
        start_boundary="# START",
        end_boundary="# END",
        expected_line_count=3,
        target_anchor=None,
        target_position="after",
        workspace_root=ws,
        target_file="existing.py",
    )

    assert "error" in result
    assert result["changed"] is False
