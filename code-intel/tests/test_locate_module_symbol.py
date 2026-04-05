"""Tests for locate_module_symbol MCP tool.

Covers:
- Find a class by name across files
- Find a function by name
- Multiple matches in different files
- No matches → empty result
- Scoped search (parent filter: Class.method)
- Variable / assignment detection
"""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.locate_module_symbol import locate_module_symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_package(tmp_path: Path, pkg_name: str, modules: dict[str, str]) -> None:
    """Create a Python package with given modules."""
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    for name, content in modules.items():
        (pkg_dir / name).write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture()
def _patch_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch workspace root and search paths."""
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.get_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.load_config",
        lambda root: {},
    )
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.get_python_search_paths",
        lambda config, root: [tmp_path / "mypkg"],
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Class search
# ---------------------------------------------------------------------------


def test_find_class_by_name(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "models.py": """\
            class UserModel:
                pass
        """,
        },
    )
    result = locate_module_symbol("UserModel")
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["kind"] == "Class"
    assert match["line"] == 1
    assert "UserModel" in match["qualified_name"]


def test_find_class_in_multiple_files(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "a.py": """\
            class Handler:
                pass
        """,
            "b.py": """\
            class Handler:
                pass
        """,
        },
    )
    result = locate_module_symbol("Handler")
    assert result["total_matches"] == 2
    files = {m["file"] for m in result["matches"]}
    assert len(files) == 2


# ---------------------------------------------------------------------------
# Function search
# ---------------------------------------------------------------------------


def test_find_function_by_name(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "utils.py": """\
            def calculate(x: int) -> int:
                return x * 2
        """,
        },
    )
    result = locate_module_symbol("calculate")
    assert result["total_matches"] == 1
    assert result["matches"][0]["kind"] == "Function"


def test_find_async_function(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "async_mod.py": """\
            async def fetch_data() -> None:
                pass
        """,
        },
    )
    result = locate_module_symbol("fetch_data")
    assert result["total_matches"] == 1
    assert result["matches"][0]["kind"] == "AsyncFunction"


# ---------------------------------------------------------------------------
# No matches
# ---------------------------------------------------------------------------


def test_no_matches(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "mod.py": """\
            def existing() -> None:
                pass
        """,
        },
    )
    result = locate_module_symbol("nonexistent_symbol")
    assert result["total_matches"] == 0
    assert result["matches"] == []


# ---------------------------------------------------------------------------
# Scoped search (Class.method)
# ---------------------------------------------------------------------------


def test_find_method_scoped_to_class(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "svc.py": """\
            class ServiceA:
                def process(self) -> None:
                    pass

            class ServiceB:
                def process(self) -> None:
                    pass
        """,
        },
    )
    result = locate_module_symbol("ServiceA.process")
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert "ServiceA" in match["qualified_name"]
    assert "process" in match["qualified_name"]


# ---------------------------------------------------------------------------
# Variables / assignments
# ---------------------------------------------------------------------------


def test_find_assignment(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "consts.py": """\
            MAX_RETRIES = 3
        """,
        },
    )
    result = locate_module_symbol("MAX_RETRIES")
    assert result["total_matches"] == 1
    assert result["matches"][0]["kind"] == "Assignment"


def test_find_annotated_variable(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "typed.py": """\
            logger: Logger = get_logger()
        """,
        },
    )
    result = locate_module_symbol("logger")
    assert result["total_matches"] == 1
    assert result["matches"][0]["kind"] == "Variable"


# ---------------------------------------------------------------------------
# Qualified name and length
# ---------------------------------------------------------------------------


def test_match_includes_length(tmp_path: Path, _patch_workspace: Path) -> None:
    _make_package(
        tmp_path,
        "mypkg",
        {
            "multi.py": """\
            class Big:
                def a(self) -> None:
                    pass

                def b(self) -> None:
                    pass

                def c(self) -> None:
                    pass
        """,
        },
    )
    result = locate_module_symbol("Big")
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["length"] > 1  # multi-line class


def test_many_matches_triggers_warning(tmp_path: Path, _patch_workspace: Path) -> None:
    """More than 5 matches produces simplified output with warning."""
    modules = {}
    for i in range(7):
        modules[f"mod{i}.py"] = "def common() -> None:\n    pass\n"
    _make_package(tmp_path, "mypkg", modules)
    result = locate_module_symbol("common")
    assert result["total_matches"] > 5
    assert "warning" in result


# ---------------------------------------------------------------------------
# Parent filter: excludes top-level functions
# ---------------------------------------------------------------------------


def test_parent_filter_excludes_top_level_function(tmp_path: Path, _patch_workspace: Path) -> None:
    """Querying Svc.run must NOT return the top-level run() function."""
    _make_package(
        tmp_path,
        "mypkg",
        {
            "dual.py": """\
            class Svc:
                def run(self) -> None:
                    pass

            def run() -> None:
                pass
        """,
        },
    )
    result = locate_module_symbol("Svc.run")
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert "Svc" in match["qualified_name"]
    assert match["kind"] in ("Function", "AsyncFunction")


# ---------------------------------------------------------------------------
# Path filter: segment-boundary matching
# ---------------------------------------------------------------------------


def test_path_filter_uses_segment_matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Querying services.Foo must NOT match microservices/."""
    # Create two separate packages: services/ and microservices/
    _make_package(
        tmp_path,
        "services",
        {
            "impl.py": """\
            class Foo:
                pass
        """,
        },
    )
    _make_package(
        tmp_path,
        "microservices",
        {
            "impl.py": """\
            class Foo:
                pass
        """,
        },
    )
    # Patch search paths to include both packages
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.get_workspace_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.load_config",
        lambda root: {},
    )
    monkeypatch.setattr(
        "mcp_code_intel.tools.locate_module_symbol.get_python_search_paths",
        lambda config, root: [tmp_path],
    )
    result = locate_module_symbol("services.Foo")
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert "services" in match["file"]
    assert "microservices" not in match["file"]
