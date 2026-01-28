"""
ML-optimized API coverage checker.

Checks which backend API endpoints are used by the frontend.
Returns structured JSON for AI consumption.
"""

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# Project root
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


def get_backend_routes() -> list[tuple[str, str]]:
    """
    Get all routes from FastAPI application.

    Returns:
        List of (method, path) tuples
    """
    from nomarr.interfaces.api.api_app import api_app

    routes = []
    for route in api_app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods_list = getattr(route, "methods", set())
            route_path = getattr(route, "path", "")

            # Skip OPTIONS (auto-generated CORS)
            for method in sorted(methods_list):
                if method != "OPTIONS":
                    routes.append((method, route_path))

    return sorted(routes, key=lambda x: (x[1], x[0]))


def scan_frontend_usage(frontend_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """
    Scan frontend TypeScript files for API endpoint usage.

    Returns:
        Dict mapping endpoint patterns to list of (file_path, line_number) tuples
    """
    usage_map: dict[str, list[tuple[str, int]]] = defaultdict(list)

    # Pattern to match API endpoint strings in TypeScript
    endpoint_pattern = re.compile(r"""["'`](/api/[^"'`\s]+)["'`]""")
    template_pattern = re.compile(r"`(/api/[^`]+)`")

    for ts_file in frontend_dir.rglob("*.ts"):
        if "node_modules" in str(ts_file):
            continue

        try:
            content = ts_file.read_text(encoding="utf-8")
            lines = content.split("\n")

            for line_num, line in enumerate(lines, start=1):
                for match in endpoint_pattern.finditer(line):
                    endpoint = match.group(1).split("?")[0]
                    rel_path = ts_file.relative_to(ROOT).as_posix()
                    usage_map[endpoint].append((rel_path, line_num))

                for match in template_pattern.finditer(line):
                    endpoint = match.group(1)
                    endpoint_base = re.sub(r"\$\{[^}]+\}", "{param}", endpoint).split("?")[0]
                    rel_path = ts_file.relative_to(ROOT).as_posix()
                    usage_map[endpoint_base].append((rel_path, line_num))

        except Exception:
            pass

    return dict(usage_map)


def normalize_path(path: str) -> str:
    """Normalize FastAPI path params like {library_id} to {param}."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


def check_api_coverage(
    filter_mode: str | None = None,
    route_path: str | None = None,
) -> dict[str, Any]:
    """
    Check API coverage between backend and frontend.

    Args:
        filter_mode: "used", "unused", or None for all
        route_path: Filter to specific route path (e.g., "/api/web/libraries")

    Returns:
        Dict with endpoints, stats, and usage information
    """
    backend_routes = get_backend_routes()
    frontend_dir = ROOT / "frontend" / "src"
    frontend_usage = scan_frontend_usage(frontend_dir)

    results = []

    for method, path in backend_routes:
        # Filter by specific route if requested
        if route_path and path != route_path:
            continue

        # Check for exact match or normalized match
        frontend_files = frontend_usage.get(path, [])
        if not frontend_files:
            normalized_path = normalize_path(path)
            for frontend_path, usages in frontend_usage.items():
                if normalize_path(frontend_path) == normalized_path:
                    frontend_files.extend(usages)

        used = len(frontend_files) > 0

        # Apply filter
        if filter_mode == "used" and not used:
            continue
        if filter_mode == "unused" and used:
            continue

        # Deduplicate usage locations
        unique_usages = sorted(set(frontend_files))

        results.append(
            {
                "method": method,
                "path": path,
                "used": used,
                "usage_count": len(unique_usages),
                "locations": [{"file": f, "line": ln} for f, ln in unique_usages],
            }
        )

    # Calculate stats
    total = len(results)
    used_count = sum(1 for r in results if r["used"])
    unused_count = total - used_count
    coverage_pct = (used_count / total * 100) if total > 0 else 0

    return {
        "stats": {
            "total": total,
            "used": used_count,
            "unused": unused_count,
            "coverage_pct": round(coverage_pct, 1),
        },
        "endpoints": results,
    }


if __name__ == "__main__":
    # CLI for testing
    import json

    result = check_api_coverage()
    print(json.dumps(result, indent=2))
