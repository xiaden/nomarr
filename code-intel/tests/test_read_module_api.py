"""Tests for read_module_api MCP tool.

Covers:
- Module with functions → returns function names + signatures
- Module with classes → returns class names + methods
- Module with __all__ → captures exports
- Nested package resolution (a.b.c)
- Module not found → error
- Syntax error in module → error
- Empty module → returns minimal API
- Type annotations in signatures preserved
- Constants extracted
- Dataclass-style fields extracted
"""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.read_module_api import read_module_api

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_package(
    tmp_path: Path, pkg_name: str, modules: dict[str, str]
) -> None:
    """Create a Python package with given modules."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    for name, content in modules.items():
        parts = name.split("/")
        if len(parts) > 1:
            sub_dir = pkg_dir / "/".join(parts[:-1])
            sub_dir.mkdir(parents=True, exist_ok=True)
            (sub_dir / "__init__.py").write_text("", encoding="utf-8")
        (pkg_dir / name).write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture()
def _patch_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch get_workspace_root to return tmp_path."""
    monkeypatch.setattr(
        "mcp_code_intel.tools.read_module_api.get_workspace_root",
        lambda: tmp_path,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def test_module_with_functions(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "funcs.py": """\
            def greet(name: str) -> str:
                \"\"\"Say hello.\"\"\"\n                return f"Hello {name}"

            async def fetch(url: str, timeout: int = 30) -> bytes:
                \"\"\"Fetch data.\"\"\"\n                return b""
        """,
    })
    result = read_module_api("mypkg.funcs")
    assert "error" not in result
    assert "functions" in result
    funcs = result["functions"]
    assert "greet" in funcs
    assert "name: str" in funcs["greet"]["sig"]
    assert "-> str" in funcs["greet"]["sig"]
    assert funcs["greet"]["doc"] == "Say hello."
    assert "fetch" in funcs
    assert "async" in funcs["fetch"]["sig"]
    assert "timeout: int = 30" in funcs["fetch"]["sig"]


def test_module_with_classes(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "models.py": """\
            class Animal:
                \"\"\"An animal.\"\"\"\n
                def speak(self) -> str:
                    \"\"\"Make sound.\"\"\"\n                    return ""

                def eat(self, food: str) -> None:
                    pass
        """,
    })
    result = read_module_api("mypkg.models")
    assert "error" not in result
    assert "classes" in result
    cls = result["classes"]["Animal"]
    assert cls["doc"] == "An animal."
    assert "speak" in cls["methods"]
    assert "eat" in cls["methods"]
    assert "food: str" in cls["methods"]["eat"]["sig"]


def test_module_with_all(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "public.py": """\
            __all__ = ["public_func"]

            def public_func() -> None:
                pass

            def _private_func() -> None:
                pass
        """,
    })
    result = read_module_api("mypkg.public")
    assert "error" not in result
    assert result["__all__"] == ["public_func"]
    # Both functions still appear in the API (tool shows all, __all__ is metadata)
    assert "public_func" in result["functions"]
    assert "_private_func" in result["functions"]


def test_nested_package_resolution(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    pkg = tmp_path / "mypkg" / "sub" / "deep"
    pkg.mkdir(parents=True)
    (tmp_path / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mypkg" / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mypkg" / "sub" / "deep" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "mypkg" / "sub" / "deep" / "leaf.py").write_text(
        textwrap.dedent("""\
            def leaf_func() -> int:
                return 42
        """),
        encoding="utf-8",
    )
    result = read_module_api("mypkg.sub.deep.leaf")
    assert "error" not in result
    assert "leaf_func" in result["functions"]


def test_module_not_found(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    result = read_module_api("nonexistent.module")
    assert "error" in result
    assert "Could not find" in result["error"]


def test_syntax_error_in_module(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "broken.py": "def broken(:\n    pass\n",
    })
    result = read_module_api("mypkg.broken")
    assert "error" in result
    assert "Syntax error" in result["error"]


def test_empty_module(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "empty.py": "\n",
    })
    result = read_module_api("mypkg.empty")
    assert "error" not in result
    assert "classes" not in result
    assert "functions" not in result


def test_type_annotations_preserved(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "typed.py": """\
            from typing import Optional

            def process(
                items: list[str],
                callback: Optional[callable] = None,
                *args: int,
                **kwargs: str,
            ) -> dict[str, int]:
                pass
        """,
    })
    result = read_module_api("mypkg.typed")
    assert "error" not in result
    sig = result["functions"]["process"]["sig"]
    assert "items: list[str]" in sig
    assert "-> dict[str, int]" in sig
    assert "*args: int" in sig
    assert "**kwargs: str" in sig


def test_constants_extracted(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "consts.py": """\
            MAX_SIZE = 100
            DEFAULT_NAME = "hello"

            def func() -> None:
                pass
        """,
    })
    result = read_module_api("mypkg.consts")
    assert "error" not in result
    assert "constants" in result
    assert result["constants"]["MAX_SIZE"] == "100"
    assert result["constants"]["DEFAULT_NAME"] == "'hello'"


def test_class_fields_extracted(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "dto.py": """\
            class Config:
                host: str
                port: int = 8080
                debug: bool = False
        """,
    })
    result = read_module_api("mypkg.dto")
    assert "error" not in result
    cls = result["classes"]["Config"]
    assert "fields" in cls
    assert cls["fields"]["host"]["type"] == "str"
    assert cls["fields"]["port"]["default"] == "8080"


def test_no_docstrings_option(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    _make_package(tmp_path, "mypkg", {
        "nodoc.py": """\
            def hello() -> None:
                \"\"\"Greeting.\"\"\"\n                pass
        """,
    })
    result = read_module_api("mypkg.nodoc", include_docstrings=False)
    assert "error" not in result
    assert "doc" not in result["functions"]["hello"]


def test_package_init_resolution(
    tmp_path: Path, _patch_workspace: Path
) -> None:
    """Resolving a package name finds __init__.py."""
    _make_package(tmp_path, "mypkg", {
        "__init__.py": """\
            PACKAGE_VERSION = "1.0"

            def init_func() -> None:
                pass
        """,
    })
    # Overwrite the empty __init__.py
    (tmp_path / "mypkg" / "__init__.py").write_text(
        textwrap.dedent("""\
            PACKAGE_VERSION = "1.0"

            def init_func() -> None:
                pass
        """),
        encoding="utf-8",
    )
    result = read_module_api("mypkg")
    assert "error" not in result
    assert "init_func" in result["functions"]
