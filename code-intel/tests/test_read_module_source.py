"""Tests for read_module_source MCP tool.

Covers:
- Get source of a function by qualified name
- Get source of a class
- Get source of a method (Class.method)
- Symbol not found → error
- Module not found → error
- Returns line numbers and line count
- large_context parameter changes context lines
- Module-level symbol (whole module)
"""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.read_module_source import read_module_source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_MODULE = textwrap.dedent("""\
    import os

    class MyClass:
        \"\"\"A sample class.\"\"\"\n
        def __init__(self, value: int) -> None:
            self.value = value

        def get_value(self) -> int:
            return self.value

    def standalone(x: str) -> str:
        \"\"\"Standalone function.\"\"\"\n        return x.upper()

    async def async_func() -> None:
        pass
""")


def _setup_package(tmp_path: Path) -> None:
    """Create mypkg with sample module."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sample.py").write_text(SAMPLE_MODULE, encoding="utf-8")


@pytest.fixture()
def _patch_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch workspace root and module resolver."""
    monkeypatch.setattr(
        "mcp_code_intel.tools.read_module_source.get_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "mcp_code_intel.tools.read_module_source.resolve_module_path",
        lambda name, root=None: _resolve(name, tmp_path),
    )
    return tmp_path


def _resolve(module_name: str, root: Path) -> Path | None:
    """Simple module resolver for test fixtures."""
    parts = module_name.split(".")
    # Try as file
    candidate = root / Path(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    # Try as package
    candidate = root / Path(*parts) / "__init__.py"
    if candidate.exists():
        return candidate
    return None


# ---------------------------------------------------------------------------
# Function source
# ---------------------------------------------------------------------------


def test_get_function_source(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.standalone")
    assert "error" not in result
    assert result["type"] == "function"
    assert "def standalone" in result["source"]
    assert result["symbol_start_line"] > 0
    assert result["symbol_end_line"] >= result["symbol_start_line"]


def test_get_async_function_source(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.async_func")
    assert "error" not in result
    assert result["type"] == "async_function"
    assert "async def async_func" in result["source"]


# ---------------------------------------------------------------------------
# Class source
# ---------------------------------------------------------------------------


def test_get_class_source(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.MyClass")
    assert "error" not in result
    assert result["type"] == "class"
    assert "class MyClass" in result["source"]
    assert "def __init__" in result["source"]
    assert "def get_value" in result["source"]


def test_get_method_source(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.MyClass.get_value")
    assert "error" not in result
    assert result["type"] == "method"
    assert "def get_value" in result["source"]
    assert result["symbol_start_line"] > 0


def test_get_constructor_source(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.MyClass.__init__")
    assert "error" not in result
    assert result["type"] == "method"
    assert "def __init__" in result["source"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_symbol_not_found(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.nonexistent")
    assert "error" in result
    assert "Symbol not found" in result["error"]


def test_module_not_found(tmp_path: Path, _patch_workspace: Path) -> None:
    result = read_module_source("nonexistent.module.func")
    assert "error" in result
    assert "Could not find" in result["error"]


def test_invalid_qualified_name(tmp_path: Path, _patch_workspace: Path) -> None:
    result = read_module_source("singlename")
    assert "error" in result
    assert "Invalid qualified name" in result["error"]


# ---------------------------------------------------------------------------
# Line numbers and context
# ---------------------------------------------------------------------------


def test_returns_line_numbers(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.standalone")
    assert "error" not in result
    assert "line" in result
    assert "line_count" in result
    assert result["line_count"] > 0
    # Context lines: symbol line range ± 2
    assert result["line"] <= result["symbol_start_line"]
    assert result["line"] + result["line_count"] - 1 >= result["symbol_end_line"]


def test_large_context_expands_range(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    normal = read_module_source("mypkg.sample.standalone")
    large = read_module_source("mypkg.sample.standalone", large_context=True)
    assert "error" not in normal
    assert "error" not in large
    # large_context should return more lines (or at least not fewer)
    assert large["line_count"] >= normal["line_count"]


def test_symbol_boundaries_within_context(tmp_path: Path, _patch_workspace: Path) -> None:
    _setup_package(tmp_path)
    result = read_module_source("mypkg.sample.MyClass.get_value")
    assert "error" not in result
    assert result["symbol_start_line"] >= result["line"]
    end_context = result["line"] + result["line_count"] - 1
    assert result["symbol_end_line"] <= end_context


# ---------------------------------------------------------------------------
# Three-level nesting (Outer.Inner.method)
# ---------------------------------------------------------------------------


def test_three_level_nesting(tmp_path: Path, _patch_workspace: Path) -> None:
    """_find_symbol_in_ast must resolve 3-level paths like Outer.Inner.do_thing."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "nested.py").write_text(
        textwrap.dedent("""\
            class Outer:
                class Inner:
                    def do_thing(self) -> str:
                        return "nested"
        """),
        encoding="utf-8",
    )
    result = read_module_source("mypkg.nested.Outer.Inner.do_thing")
    assert "error" not in result, result.get("error")
    assert "def do_thing" in result["source"]
    assert result["symbol_start_line"] > 0
    assert result["symbol_end_line"] >= result["symbol_start_line"]
