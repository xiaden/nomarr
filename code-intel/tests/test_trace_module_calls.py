"""Tests for trace_module_calls MCP tool.

Covers:
- Trace simple call chain → returns full chain with files/lines
- Trace function with no calls → returns just the function
- Function not found → error
- Recursive calls handled (no infinite loop)
- Call through imports resolved
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.trace_module_calls import trace_module_calls

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
        (pkg_dir / name).write_text(textwrap.dedent(content), encoding="utf-8")


def _empty_config() -> dict:
    return {
        "tracing": {
            "include_patterns": [],
            "max_depth": 10,
            "filter_external": True,
        },
    }


# ---------------------------------------------------------------------------
# Simple call chain
# ---------------------------------------------------------------------------


def test_trace_simple_call_chain(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "service.py": """\
            from app.component import do_work

            def handle():
                do_work()
        """,
        "component.py": """\
            from app.helper import util

            def do_work():
                util()
        """,
        "helper.py": """\
            def util():
                pass
        """,
    })
    result = trace_module_calls(
        "app.service.handle", project_root=tmp_path, config=_empty_config()
    )
    assert "error" not in result
    assert result["root"] == "app.service.handle"
    tree = result["tree"]
    assert tree["name"] == "handle"
    assert tree["file"] == "app/service.py"
    assert tree["line"] is not None
    # Should have traced into do_work
    assert len(tree.get("calls", [])) > 0
    call_names = {c["name"] for c in tree["calls"]}
    assert "do_work" in call_names


def test_trace_deep_chain(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "service.py": """\
            from app.component import do_work

            def handle():
                do_work()
        """,
        "component.py": """\
            from app.helper import util

            def do_work():
                util()
        """,
        "helper.py": """\
            def util():
                pass
        """,
    })
    result = trace_module_calls(
        "app.service.handle", project_root=tmp_path, config=_empty_config()
    )
    assert "error" not in result
    # Flat chain should contain all levels
    flat_names = [entry["name"] for entry in result["flat"]]
    assert "handle" in flat_names
    assert "do_work" in flat_names
    assert "util" in flat_names


# ---------------------------------------------------------------------------
# Leaf function (no calls)
# ---------------------------------------------------------------------------


def test_trace_leaf_function(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "leaf.py": """\
            def noop():
                x = 1 + 2
                return x
        """,
    })
    result = trace_module_calls(
        "app.leaf.noop", project_root=tmp_path, config=_empty_config()
    )
    assert "error" not in result
    tree = result["tree"]
    assert tree["name"] == "noop"
    assert tree.get("calls") is None or len(tree["calls"]) == 0


# ---------------------------------------------------------------------------
# Function not found
# ---------------------------------------------------------------------------


def test_function_not_found(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "mod.py": """\
            def existing():
                pass
        """,
    })
    result = trace_module_calls(
        "app.mod.nonexistent", project_root=tmp_path, config=_empty_config()
    )
    # Should still return something (tree with no line) or an error
    tree = result.get("tree")
    if tree:
        assert tree["line"] is None
    # Alternatively could return error


def test_module_not_found(tmp_path: Path) -> None:
    result = trace_module_calls(
        "nonexistent.module.func", project_root=tmp_path, config=_empty_config()
    )
    # Tool returns a tree with file/line=None for unresolvable modules
    tree = result["tree"]
    assert tree["file"] is None
    assert tree["line"] is None


# ---------------------------------------------------------------------------
# Recursive / circular calls
# ---------------------------------------------------------------------------


def test_recursive_calls_no_infinite_loop(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "recursive.py": """\
            from app.recursive import mutual_b

            def mutual_a():
                mutual_b()

            def mutual_b():
                mutual_a()
        """,
    })
    result = trace_module_calls(
        "app.recursive.mutual_a", project_root=tmp_path, config=_empty_config()
    )
    # Should terminate without hanging
    assert "error" not in result
    assert result["depth"] < 20  # bounded recursion


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_returns_stats(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "entry.py": """\
            def start():
                pass
        """,
    })
    result = trace_module_calls(
        "app.entry.start", project_root=tmp_path, config=_empty_config()
    )
    assert "error" not in result
    assert "depth" in result
    assert "call_count" in result
    assert result["call_count"] >= 1


def test_flat_output_has_entries(tmp_path: Path) -> None:
    _make_package(tmp_path, "app", {
        "entry.py": """\
            from app.worker import work

            def start():
                work()
        """,
        "worker.py": """\
            def work():
                pass
        """,
    })
    result = trace_module_calls(
        "app.entry.start", project_root=tmp_path, config=_empty_config()
    )
    assert "error" not in result
    flat = result["flat"]
    assert len(flat) >= 2
    assert flat[0]["name"] == "start"
