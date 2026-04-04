"""Tests for search_file_text tool."""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.search_file_text import search_file_text


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


def test_single_match_with_context(ws: Path) -> None:
    """Find a single match and return 2-line context."""
    content = textwrap.dedent("""\
        line 1
        line 2
        TARGET
        line 4
        line 5
    """)
    _make_file(ws, "f.txt", content)

    result = search_file_text("f.txt", "TARGET", workspace_root=ws)

    assert "error" not in result
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["line_number"] == 3
    # Context should include surrounding lines
    assert "line 2" in match["content"]
    assert "line 4" in match["content"]


def test_multiple_matches_in_one_file(ws: Path) -> None:
    """Find multiple occurrences of the search string."""
    content = "aaa\nfoo\nbbb\nfoo\nccc\n"
    _make_file(ws, "f.txt", content)

    result = search_file_text("f.txt", "foo", workspace_root=ws)

    assert result["total_matches"] == 2
    assert result["matches"][0]["line_number"] == 2
    assert result["matches"][1]["line_number"] == 4


def test_no_matches(ws: Path) -> None:
    """Search string not found → empty matches, no error."""
    _make_file(ws, "f.txt", "hello world\n")

    result = search_file_text("f.txt", "NONEXISTENT", workspace_root=ws)

    assert "error" not in result
    assert result["total_matches"] == 0
    assert result["matches"] == []


def test_context_at_file_start(ws: Path) -> None:
    """Match on line 1 — context shouldn't go below line 1."""
    content = "TARGET\nline 2\nline 3\nline 4\n"
    _make_file(ws, "f.txt", content)

    result = search_file_text("f.txt", "TARGET", workspace_root=ws)

    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["line_number"] == 1
    assert "(start)" in match["line_range"] or match["line_range"].startswith("1-")


def test_context_at_file_end(ws: Path) -> None:
    """Match on last line — context shouldn't go past EOF."""
    content = "line 1\nline 2\nline 3\nTARGET\n"
    _make_file(ws, "f.txt", content)

    result = search_file_text("f.txt", "TARGET", workspace_root=ws)

    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["line_number"] == 4


def test_case_sensitive_search(ws: Path) -> None:
    """Search is case-sensitive by default."""
    _make_file(ws, "f.txt", "Hello\nhello\nHELLO\n")

    result = search_file_text("f.txt", "hello", workspace_root=ws)

    assert result["total_matches"] == 1
    assert result["matches"][0]["line_number"] == 2


# -- Error cases --


def test_file_not_found(ws: Path) -> None:
    """File doesn't exist → error."""
    result = search_file_text("missing.txt", "x", workspace_root=ws)

    assert "error" in result


def test_empty_search_string(ws: Path) -> None:
    """Empty search string → error."""
    _make_file(ws, "f.txt", "content\n")

    result = search_file_text("f.txt", "", workspace_root=ws)

    assert "error" in result


def test_path_outside_workspace(ws: Path) -> None:
    """Path traversal outside workspace → error."""
    result = search_file_text("../../etc/passwd", "root", workspace_root=ws)

    assert "error" in result


def test_binary_file_handling(ws: Path) -> None:
    """Non-UTF-8 file → error."""
    p = ws / "binary.dat"
    p.write_bytes(b"\x00\x01\x80\xff")

    result = search_file_text("binary.dat", "test", workspace_root=ws)

    assert "error" in result


def test_directory_not_file(ws: Path) -> None:
    """Path is a directory, not a file → error."""
    (ws / "somedir").mkdir()

    result = search_file_text("somedir", "x", workspace_root=ws)

    assert "error" in result
