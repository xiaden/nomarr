#!/usr/bin/env python3
"""List all API routes from the FastAPI application."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import after path setup (noqa required for ruff)
from nomarr.interfaces.api.api_app import api_app  # noqa: E402


def list_routes():
    """List all routes from the FastAPI app."""
    routes = []

    for route in api_app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods_list = getattr(route, "methods", set())
            route_path = getattr(route, "path", "")
            methods = ", ".join(sorted(methods_list))
            routes.append((route_path, methods))

    # Sort by path
    routes.sort(key=lambda x: x[0])

    # Group by prefix
    integration_routes = [r for r in routes if r[0].startswith("/api/v1")]
    web_routes = [r for r in routes if r[0].startswith("/api/web")]
    root_routes = [r for r in routes if not r[0].startswith("/api/")]

    print("=" * 80)
    print("INTEGRATION API (/api/v1)")
    print("=" * 80)
    for path, methods in integration_routes:
        print(f"{methods:20s} {path}")

    print("\n" + "=" * 80)
    print("WEB UI API (/api/web)")
    print("=" * 80)
    for path, methods in web_routes:
        print(f"{methods:20s} {path}")

    print("\n" + "=" * 80)
    print("ROOT ROUTES")
    print("=" * 80)
    for path, methods in root_routes:
        print(f"{methods:20s} {path}")

    print("\n" + "=" * 80)
    print(f"TOTAL: {len(routes)} routes")
    print(f"  Integration: {len(integration_routes)}")
    print(f"  Web UI: {len(web_routes)}")
    print(f"  Root: {len(root_routes)}")
    print("=" * 80)


if __name__ == "__main__":
    list_routes()
