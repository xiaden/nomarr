"""Tests for trace_project_endpoint MCP tool.

Covers:
- Trace endpoint through Depends → shows service calls
- Endpoint not found → error
- Multiple endpoints, find specific one
- Endpoint with no DI
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.trace_project_endpoint import trace_project_endpoint

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


def _default_config() -> dict:
    return {
        "backend": {
            "dependency_injection": {
                "patterns": ["Depends("],
            },
        },
        "tracing": {
            "include_patterns": [],
            "max_depth": 10,
            "filter_external": True,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint with Depends
# ---------------------------------------------------------------------------


def test_trace_endpoint_with_depends(tmp_path: Path) -> None:
    _make_package(tmp_path, "myapp", {
        "deps.py": """\
            from myapp.services import ItemService

            def get_item_service() -> ItemService:
                return ItemService()
        """,
        "services.py": """\
            class ItemService:
                def list_items(self) -> list:
                    return []

                def get_item(self, item_id: str) -> dict:
                    return {}
        """,
        "router.py": """\
            from fastapi import APIRouter, Depends
            from myapp.deps import get_item_service

            router = APIRouter()

            @router.get("/items")
            def get_items(svc=Depends(get_item_service)):
                return svc.list_items()
        """,
    })
    result = trace_project_endpoint(
        "myapp.router.get_items",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" not in result
    assert result["endpoint"]["name"] == "myapp.router.get_items"
    assert result["endpoint"]["line"] is not None
    # Should detect the Depends injection
    assert len(result["dependencies"]) == 1
    dep = result["dependencies"][0]
    assert dep["param"] == "svc"
    assert dep["depends_on"] == "get_item_service"
    # Should detect service method calls
    assert "svc" in result["service_calls"]
    assert "list_items" in result["service_calls"]["svc"]


def test_trace_endpoint_resolved_type(tmp_path: Path) -> None:
    _make_package(tmp_path, "myapp", {
        "deps.py": """\
            from myapp.services import ItemService

            def get_item_service() -> ItemService:
                return ItemService()
        """,
        "services.py": """\
            class ItemService:
                def list_items(self) -> list:
                    return []
        """,
        "router.py": """\
            from fastapi import APIRouter, Depends
            from myapp.deps import get_item_service

            router = APIRouter()

            @router.get("/items")
            def get_items(svc=Depends(get_item_service)):
                return svc.list_items()
        """,
    })
    result = trace_project_endpoint(
        "myapp.router.get_items",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" not in result
    dep = result["dependencies"][0]
    # Should resolve the return type of get_item_service
    assert dep["resolved_type"] is not None
    assert "ItemService" in dep["resolved_type"]


# ---------------------------------------------------------------------------
# Endpoint not found
# ---------------------------------------------------------------------------


def test_endpoint_not_found(tmp_path: Path) -> None:
    _make_package(tmp_path, "myapp", {
        "router.py": """\
            def existing():
                pass
        """,
    })
    result = trace_project_endpoint(
        "myapp.router.nonexistent",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" in result


def test_module_not_found(tmp_path: Path) -> None:
    result = trace_project_endpoint(
        "nonexistent.module.endpoint",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# Endpoint with no DI
# ---------------------------------------------------------------------------


def test_endpoint_no_dependencies(tmp_path: Path) -> None:
    _make_package(tmp_path, "myapp", {
        "router.py": """\
            from fastapi import APIRouter

            router = APIRouter()

            @router.get("/health")
            def health_check():
                return {"status": "ok"}
        """,
    })
    result = trace_project_endpoint(
        "myapp.router.health_check",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" not in result
    assert result["dependencies"] == []
    assert result["endpoint"]["name"] == "myapp.router.health_check"


# ---------------------------------------------------------------------------
# Multiple service method calls
# ---------------------------------------------------------------------------


def test_multiple_service_method_calls(tmp_path: Path) -> None:
    _make_package(tmp_path, "myapp", {
        "deps.py": """\
            from myapp.services import ItemService

            def get_item_service() -> ItemService:
                return ItemService()
        """,
        "services.py": """\
            class ItemService:
                def list_items(self) -> list:
                    return []

                def count_items(self) -> int:
                    return 0
        """,
        "router.py": """\
            from fastapi import APIRouter, Depends
            from myapp.deps import get_item_service

            router = APIRouter()

            @router.get("/items/summary")
            def items_summary(svc=Depends(get_item_service)):
                items = svc.list_items()
                count = svc.count_items()
                return {"items": items, "count": count}
        """,
    })
    result = trace_project_endpoint(
        "myapp.router.items_summary",
        project_root=tmp_path,
        config=_default_config(),
    )
    assert "error" not in result
    svc_calls = result["service_calls"]["svc"]
    assert "list_items" in svc_calls
    assert "count_items" in svc_calls
