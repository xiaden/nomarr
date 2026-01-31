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

__all__ = ["list_routes"]

from pathlib import Path
from typing import Any

from scripts.mcp.tools.helpers.route_parser import build_full_paths, parse_interface_files


def _get_interfaces_dir(project_root: Path) -> Path:
    """Get the interfaces/api directory."""
    return project_root / "nomarr" / "interfaces" / "api"


def list_routes(project_root: Path | None = None) -> dict[str, Any]:
    """List all API routes by static analysis.

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
        project_root = Path(__file__).parent.parent.parent.parent

    interfaces_dir = _get_interfaces_dir(project_root)

    if not interfaces_dir.exists():
        return {"error": f"Interfaces directory not found: {interfaces_dir}"}

    # Parse all interface files
    routers = parse_interface_files(interfaces_dir)

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
