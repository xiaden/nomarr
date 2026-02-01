#!/usr/bin/env python3
"""List all API routes from the FastAPI application."""

import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class RouteInfo:
    """Information about a single route."""

    path: str
    methods: str


@dataclass
class RoutesResult:
    """Result of listing routes."""

    integration_routes: list[RouteInfo]
    web_routes: list[RouteInfo]
    root_routes: list[RouteInfo]

    @property
    def total(self) -> int:
        return len(self.integration_routes) + len(self.web_routes) + len(self.root_routes)


def get_routes() -> RoutesResult:
    """Get all routes from the FastAPI app, grouped by prefix."""
    # Lazy import to avoid module-level side effects
    from nomarr.interfaces.api.api_app import api_app

    routes = []

    for route in api_app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods_list = getattr(route, "methods", set())
            route_path = getattr(route, "path", "")
            methods = ", ".join(sorted(methods_list))
            routes.append(RouteInfo(path=route_path, methods=methods))

    # Sort by path
    routes.sort(key=lambda x: x.path)

    # Group by prefix
    return RoutesResult(
        integration_routes=[r for r in routes if r.path.startswith("/api/v1")],
        web_routes=[r for r in routes if r.path.startswith("/api/web")],
        root_routes=[r for r in routes if not r.path.startswith("/api/")],
    )


def format_routes(result: RoutesResult) -> str:
    """Format routes as text."""
    lines = []

    lines.append("=" * 80)
    lines.append("INTEGRATION API (/api/v1)")
    lines.append("=" * 80)
    for r in result.integration_routes:
        lines.append(f"{r.methods:20s} {r.path}")

    lines.append("")
    lines.append("=" * 80)
    lines.append("WEB UI API (/api/web)")
    lines.append("=" * 80)
    for r in result.web_routes:
        lines.append(f"{r.methods:20s} {r.path}")

    lines.append("")
    lines.append("=" * 80)
    lines.append("ROOT ROUTES")
    lines.append("=" * 80)
    for r in result.root_routes:
        lines.append(f"{r.methods:20s} {r.path}")

    lines.append("")
    lines.append("=" * 80)
    lines.append(f"TOTAL: {result.total} routes")
    lines.append(f"  Integration: {len(result.integration_routes)}")
    lines.append(f"  Web UI: {len(result.web_routes)}")
    lines.append(f"  Root: {len(result.root_routes)}")
    lines.append("=" * 80)

    return "\n".join(lines)


def list_routes() -> None:
    """List all routes (prints to stdout)."""
    result = get_routes()
    print(format_routes(result))


if __name__ == "__main__":
    list_routes()
