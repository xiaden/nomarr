"""Tests for edit_file_replace_string tool."""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_replace_string import edit_file_replace_string


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


def test_single_replacement(ws: Path) -> None:
    """Single replacement with expected_count=1."""
    _make_file(ws, "f.py", "hello world\n")

    result = edit_file_replace_string(
        "f.py",
        [{"old_string": "hello", "new_string": "goodbye", "expected_count": 1}],
        workspace_root=ws,
    )

    assert result["changed"] is True
    assert result["replacements_applied"] == 1
    assert (ws / "f.py").read_text() == "goodbye world\n"


def test_multiple_replacements_in_one_call(ws: Path) -> None:
    """Apply two non-overlapping replacements atomically."""
    content = textwrap.dedent("""\
        def foo():
            return 1

        def bar():
            return 2
    """)
    _make_file(ws, "f.py", content)

    result = edit_file_replace_string(
        "f.py",
        [
            {"old_string": "return 1", "new_string": "return 10", "expected_count": 1},
            {"old_string": "return 2", "new_string": "return 20", "expected_count": 1},
        ],
        workspace_root=ws,
    )

    assert result["changed"] is True
    assert result["replacements_applied"] == 2
    new_content = (ws / "f.py").read_text()
    assert "return 10" in new_content
    assert "return 20" in new_content


def test_empty_replacement_deletes_text(ws: Path) -> None:
    """Replacing with empty string effectively deletes the match."""
    _make_file(ws, "f.txt", "keep DELETE_ME keep\n")

    result = edit_file_replace_string(
        "f.txt",
        [{"old_string": "DELETE_ME ", "new_string": "", "expected_count": 1}],
        workspace_root=ws,
    )

    assert result["changed"] is True
    assert (ws / "f.txt").read_text() == "keep keep\n"


def test_expected_count_greater_than_one(ws: Path) -> None:
    """Replace a string that appears multiple times."""
    _make_file(ws, "f.txt", "aaa bbb aaa bbb aaa\n")

    result = edit_file_replace_string(
        "f.txt",
        [{"old_string": "aaa", "new_string": "ccc", "expected_count": 3}],
        workspace_root=ws,
    )

    assert result["changed"] is True
    assert (ws / "f.txt").read_text() == "ccc bbb ccc bbb ccc\n"


def test_preserves_rest_of_file(ws: Path) -> None:
    """Replacement only changes matched text; rest is untouched."""
    content = "line1\nTARGET\nline3\n"
    _make_file(ws, "f.txt", content)

    edit_file_replace_string(
        "f.txt",
        [{"old_string": "TARGET", "new_string": "REPLACED", "expected_count": 1}],
        workspace_root=ws,
    )

    assert (ws / "f.txt").read_text() == "line1\nREPLACED\nline3\n"


# -- Error cases --


def test_count_mismatch_found_more(ws: Path) -> None:
    """Found 2 matches but expected 1 → error, no changes."""
    _make_file(ws, "f.txt", "aaa bbb aaa\n")

    result = edit_file_replace_string(
        "f.txt",
        [{"old_string": "aaa", "new_string": "ccc", "expected_count": 1}],
        workspace_root=ws,
    )

    assert result["changed"] is False
    assert "error" in result or "validation_errors" in result
    # File untouched
    assert (ws / "f.txt").read_text() == "aaa bbb aaa\n"


def test_string_not_found(ws: Path) -> None:
    """old_string not present → error, no changes."""
    _make_file(ws, "f.txt", "hello\n")

    result = edit_file_replace_string(
        "f.txt",
        [{"old_string": "nonexistent", "new_string": "x", "expected_count": 1}],
        workspace_root=ws,
    )

    assert result["changed"] is False
    assert "error" in result or "validation_errors" in result


def test_file_not_found(ws: Path) -> None:
    """File doesn't exist → error."""
    result = edit_file_replace_string(
        "missing.py",
        [{"old_string": "a", "new_string": "b", "expected_count": 1}],
        workspace_root=ws,
    )

    assert "error" in result


def test_no_replacements_provided(ws: Path) -> None:
    """Empty replacements list → error."""
    _make_file(ws, "f.txt", "content\n")

    result = edit_file_replace_string(
        "f.txt",
        [],
        workspace_root=ws,
    )

    assert "error" in result


def test_overlapping_replacements_error(ws: Path) -> None:
    """Two replacements whose spans overlap → error, no changes."""
    _make_file(ws, "f.txt", "abcdef\n")

    result = edit_file_replace_string(
        "f.txt",
        [
            {"old_string": "abcd", "new_string": "XXXX", "expected_count": 1},
            {"old_string": "cdef", "new_string": "YYYY", "expected_count": 1},
        ],
        workspace_root=ws,
    )

    assert result["changed"] is False
    assert "error" in result or "validation_errors" in result
    # File untouched
    assert (ws / "f.txt").read_text() == "abcdef\n"


def test_missing_expected_count_field(ws: Path) -> None:
    """Replacement without expected_count → validation error."""
    _make_file(ws, "f.txt", "hello\n")

    result = edit_file_replace_string(
        "f.txt",
        [{"old_string": "hello", "new_string": "bye"}],
        workspace_root=ws,
    )

    assert "error" in result
