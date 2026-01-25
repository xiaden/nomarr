#!/usr/bin/env python3
"""
ML-optimized Route Discovery Tool (Standalone)

Self-contained module for discovering API routes by static analysis.
Parses route decorators without importing the FastAPI app (which hangs in MCP).

This is intentionally decoupled from other scripts so changes don't break the MCP server.

Usage:
    # Standalone
    python scripts/mcp/list_routes_ml.py

    # As module
    from scripts.mcp.list_routes_ml import list_routes
    result = list_routes()
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RouteInfo:
    """Information about a single route."""

    method: str
    path: str
    function: str
    file: str
    line: int


@dataclass
class RouterInfo:
    """Information about a router and its routes."""

    prefix: str
    file: str
    routes: list[RouteInfo] = field(default_factory=list)


def _extract_string_value(node: ast.expr) -> str | None:
    """Extract string value from AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse_router_definition(node: ast.Assign, file_path: Path) -> RouterInfo | None:
    """Parse APIRouter() definition to extract prefix."""
    if not node.targets or not isinstance(node.targets[0], ast.Name):
        return None

    var_name = node.targets[0].id
    if var_name != "router":
        return None

    if not isinstance(node.value, ast.Call):
        return None

    call = node.value
    if not isinstance(call.func, ast.Name) or call.func.id != "APIRouter":
        return None

    # Extract prefix from keywords
    prefix = ""
    for kw in call.keywords:
        if kw.arg == "prefix":
            prefix = _extract_string_value(kw.value) or ""
            break

    return RouterInfo(prefix=prefix, file=str(file_path))


def _parse_route_decorator(
    decorator: ast.expr, func_def: ast.FunctionDef | ast.AsyncFunctionDef
) -> tuple[str, str] | None:
    """Parse @router.get("/path") style decorators."""
    if not isinstance(decorator, ast.Call):
        return None

    if not isinstance(decorator.func, ast.Attribute):
        return None

    attr = decorator.func
    if not isinstance(attr.value, ast.Name) or attr.value.id != "router":
        return None

    method = attr.attr.upper()
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
        return None

    # Get path from first positional argument
    if not decorator.args:
        return None

    path = _extract_string_value(decorator.args[0])
    if path is None:
        return None

    return (method, path)


def _parse_file(file_path: Path) -> RouterInfo | None:
    """Parse a single Python file for router and route definitions."""
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return None

    router_info: RouterInfo | None = None

    for node in ast.walk(tree):
        # Look for router = APIRouter(prefix="/...")
        if isinstance(node, ast.Assign):
            parsed = _parse_router_definition(node, file_path)
            if parsed:
                router_info = parsed

    if router_info is None:
        return None

    # Now walk again for route decorators
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                route = _parse_route_decorator(decorator, node)
                if route:
                    method, path = route
                    router_info.routes.append(
                        RouteInfo(
                            method=method,
                            path=path,
                            function=node.name,
                            file=str(file_path),
                            line=node.lineno,
                        )
                    )

    return router_info if router_info.routes else None


def _get_interfaces_dir(project_root: Path) -> Path:
    """Get the interfaces/api directory."""
    return project_root / "nomarr" / "interfaces" / "api"


def _build_full_paths(routers: list[RouterInfo], project_root: Path) -> list[dict[str, Any]]:
    """Build full paths by combining parent router prefixes."""
    # Parse router.py to understand the router hierarchy
    # web/router.py includes all web routers with /api/web prefix
    # api_app.py includes v1 routers with /api prefix

    result: list[dict[str, Any]] = []

    for router in routers:
        file_rel = Path(router.file).relative_to(project_root)
        file_str = str(file_rel).replace("\\", "/")

        # Determine parent prefix based on file location
        if "/api/web/" in file_str:
            parent_prefix = "/api/web"
        elif "/api/v1/" in file_str:
            parent_prefix = "/api"
        else:
            parent_prefix = ""

        for route in router.routes:
            full_path = parent_prefix + router.prefix + route.path
            # Clean up double slashes
            full_path = re.sub(r"//+", "/", full_path)

            result.append(
                {
                    "method": route.method,
                    "path": full_path,
                    "function": route.function,
                    "file": file_str,
                    "line": route.line,
                }
            )

    # Sort by path, then method
    result.sort(key=lambda x: (x["path"], x["method"]))
    return result


def list_routes(project_root: Path | None = None) -> dict[str, Any]:
    """
    List all API routes by static analysis.

    Args:
        project_root: Path to project root. Defaults to auto-detect.

    Returns:
        Dict with:
            - routes: List of {method, path, function, file, line}
            - by_prefix: Routes grouped by API prefix
            - total: Total route count
            - error: Optional error message
    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    interfaces_dir = _get_interfaces_dir(project_root)

    if not interfaces_dir.exists():
        return {"error": f"Interfaces directory not found: {interfaces_dir}"}

    # Find all interface files
    interface_files = list(interfaces_dir.rglob("*_if.py"))

    routers: list[RouterInfo] = []
    for file_path in interface_files:
        router = _parse_file(file_path)
        if router:
            routers.append(router)

    # Build full paths
    routes = _build_full_paths(routers, project_root)

    # Group by prefix
    by_prefix: dict[str, list[dict[str, Any]]] = {
        "integration": [],  # /api/v1
        "web": [],  # /api/web
        "other": [],
    }

    for route in routes:
        path = route["path"]
        if path.startswith("/api/v1"):
            by_prefix["integration"].append(route)
        elif path.startswith("/api/web"):
            by_prefix["web"].append(route)
        else:
            by_prefix["other"].append(route)

    return {
        "routes": routes,
        "by_prefix": by_prefix,
        "total": len(routes),
        "summary": {
            "integration": len(by_prefix["integration"]),
            "web": len(by_prefix["web"]),
            "other": len(by_prefix["other"]),
        },
    }


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="List API routes by static analysis")
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    result = list_routes(project_root)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        # Text format
        if "error" in result:
            print(f"ERROR: {result['error']}")
            return 1

        for prefix_name, routes in result["by_prefix"].items():
            if not routes:
                continue
            print(f"\n{'=' * 60}")
            print(f"{prefix_name.upper()} ({len(routes)} routes)")
            print("=" * 60)
            for r in routes:
                print(f"  {r['method']:7s} {r['path']}")
                print(f"          -> {r['function']}() in {r['file']}:{r['line']}")

        print(f"\n{'=' * 60}")
        print(f"TOTAL: {result['total']} routes")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
