#!/usr/bin/env python3
"""ML-optimized Route Discovery Tool.

Discovers API routes by static AST analysis.
Uses helpers/route_parser.py for parsing logic.

Usage:
    # Standalone
    python scripts/mcp/tools/list_routes.py

    # As module
    from scripts.mcp.tools.list_routes import list_routes
    result = list_routes()
"""

from __future__ import annotations

__all__ = ["project_list_routes"]

from pathlib import Path
from typing import Any

from .helpers.config_loader import (
    get_backend_config,
    load_config,
)
from .helpers.route_parser import build_full_paths, parse_interface_files


def _extract_route_objects(decorators: list[str]) -> set[str]:
    """Extract route object names from decorator patterns.

    Args:
        decorators: List of decorator patterns like ["@router.get", "@router.post"]

    Returns:
        Set of object names like {"router"}

    """
    route_objects: set[str] = set()
    for decorator in decorators:
        # Strip @ and extract object name before first dot
        # E.g., "@router.get" -> "router"
        if "@" in decorator and "." in decorator:
            obj_name = decorator.replace("@", "").split(".")[0]
            route_objects.add(obj_name)
    return route_objects if route_objects else {"router"}


def _get_interfaces_dir(project_root: Path) -> Path:
    """Get the interfaces/api directory."""
    return project_root / "nomarr" / "interfaces" / "api"


def project_list_routes(
    project_root: Path | None = None, config: dict | None = None
) -> dict[str, Any]:
    """List all API routes by static analysis.

    Parses route decorators from source files to discover API endpoints.
    Uses configuration to determine which decorator patterns to look for.

    Configuration used:
        backend.routes.decorators: List of route decorator patterns
            Example: ["@router.get", "@router.post", "@app.get", "@app.post"]
            Default: ["@router.get", "@router.post", "@router.put", "@router.delete", "@router.patch"]

    Args:
        project_root: Path to project root. Defaults to auto-detect.
        config: Optional config dict. If not provided, loaded from project_root.
            Can be obtained from: load_config(project_root)

    Returns:
        Dict with:
            - routes: List of {method, path, function, file, line}
            - by_prefix: Routes grouped by API prefix
            - total: Total route count
            - summary: Count per prefix (integration, web, other)
            - error: Optional error message

    """
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent.parent

    interfaces_dir = _get_interfaces_dir(project_root)

    if not interfaces_dir.exists():
        return {"error": f"Interfaces directory not found: {interfaces_dir}"}

    # Load config if not provided (dependency injection)
    if config is None:
        config = load_config(project_root)
    backend_config = get_backend_config(config)

    # Extract route object names from decorator patterns
    decorators: list[str] = backend_config.get("routes", {}).get("decorators", [])
    route_objects = _extract_route_objects(decorators)

    # Parse all interface files with config-based route objects
    routers = parse_interface_files(interfaces_dir, route_objects=route_objects)

    # Build full paths
    routes = build_full_paths(routers, project_root)

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
