"""Tests for read_file_symbol_at_line MCP tool.

Covers:
- Line inside function → returns function
- Line inside method → returns method (innermost)
- Line inside class but outside methods → returns class
- Line outside any symbol → appropriate response
- Non-Python file → error
- File not found → error
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.read_file_symbol_at_line import read_file_symbol_at_line

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_MODULE = textwrap.dedent("""\
    import os

    X = 42

    def standalone_func():
        x = 1
        return x

    class MyClass:
        class_var = "hello"

        def method_one(self):
            return 1

        def method_two(self):
            return 2

        class InnerClass:
            def inner_method(self):
                return "inner"

    def another_func():
        pass
""")


def _write_py(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Function detection
# ---------------------------------------------------------------------------


def test_line_in_function(tmp_path: Path) -> None:
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=6, workspace_root=tmp_path)
    assert "error" not in result
    assert result["qualified_name"] == "standalone_func"
    assert result["kind"] == "Function"
    assert "x = 1" in result["source"]


def test_line_on_function_def(tmp_path: Path) -> None:
    """Line on the 'def' line itself should still match."""
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=5, workspace_root=tmp_path)
    assert "error" not in result
    assert result["qualified_name"] == "standalone_func"


# ---------------------------------------------------------------------------
# Method detection (innermost)
# ---------------------------------------------------------------------------


def test_line_in_method(tmp_path: Path) -> None:
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=13, workspace_root=tmp_path)
    assert "error" not in result
    assert result["qualified_name"] == "MyClass.method_one"
    assert result["kind"] == "Method"


def test_line_in_second_method(tmp_path: Path) -> None:
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=16, workspace_root=tmp_path)
    assert "error" not in result
    assert result["qualified_name"] == "MyClass.method_two"


def test_line_in_inner_class_method(tmp_path: Path) -> None:
    """Innermost symbol wins: InnerClass.inner_method, not MyClass."""
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=20, workspace_root=tmp_path)
    assert "error" not in result
    assert "inner_method" in result["qualified_name"]


# ---------------------------------------------------------------------------
# Class detection (outside methods)
# ---------------------------------------------------------------------------


def test_line_in_class_body_no_method(tmp_path: Path) -> None:
    """Line on class_var (inside class but outside any method)."""
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=10, workspace_root=tmp_path)
    assert "error" not in result
    assert result["qualified_name"] == "MyClass"
    assert result["kind"] == "Class"


# ---------------------------------------------------------------------------
# Module-level / outside symbols
# ---------------------------------------------------------------------------


def test_line_outside_any_symbol(tmp_path: Path) -> None:
    """Line on module-level code (e.g., X = 42) → error with hint."""
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=3, workspace_root=tmp_path)
    assert "error" in result
    assert "hint" in result
    assert "source" in result  # Should still return the line with context


def test_line_on_import(tmp_path: Path) -> None:
    """Import line is module-level → error with source context."""
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=1, workspace_root=tmp_path)
    assert "error" in result
    assert "source" in result


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_non_python_file(tmp_path: Path) -> None:
    (tmp_path / "data.txt").write_text("hello\n", encoding="utf-8")
    result = read_file_symbol_at_line(file_path="data.txt", line_number=1, workspace_root=tmp_path)
    assert "error" in result


def test_file_not_found(tmp_path: Path) -> None:
    result = read_file_symbol_at_line(file_path="ghost.py", line_number=1, workspace_root=tmp_path)
    assert "error" in result


def test_path_outside_workspace(tmp_path: Path) -> None:
    result = read_file_symbol_at_line(
        file_path="../../etc/shadow", line_number=1, workspace_root=tmp_path
    )
    assert "error" in result


def test_syntax_error_file(tmp_path: Path) -> None:
    """File with syntax error should return error, not crash."""
    _write_py(tmp_path, "bad.py", "def broken(:\n    pass\n")
    result = read_file_symbol_at_line(file_path="bad.py", line_number=1, workspace_root=tmp_path)
    assert "error" in result


# ---------------------------------------------------------------------------
# Async function detection
# ---------------------------------------------------------------------------


def test_async_function(tmp_path: Path) -> None:
    code = textwrap.dedent("""\
        async def async_handler():
            return await something()
    """)
    _write_py(tmp_path, "async_mod.py", code)
    result = read_file_symbol_at_line(
        file_path="async_mod.py", line_number=2, workspace_root=tmp_path
    )
    assert "error" not in result
    assert result["qualified_name"] == "async_handler"
    assert result["kind"] == "AsyncFunction"


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


def test_response_has_file_field(tmp_path: Path) -> None:
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=6, workspace_root=tmp_path)
    assert "file" in result
    assert result["file"] == "mod.py"


def test_response_has_line_boundaries(tmp_path: Path) -> None:
    _write_py(tmp_path, "mod.py", SAMPLE_MODULE)
    result = read_file_symbol_at_line(file_path="mod.py", line_number=6, workspace_root=tmp_path)
    assert "start_line" in result
    assert "end_line" in result
    assert result["start_line"] <= 6
    assert result["end_line"] >= 6
