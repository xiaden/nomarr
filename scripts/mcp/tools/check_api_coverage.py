"""ML-optimized API coverage checker.

Checks which backend API endpoints are used by the frontend.
Returns structured JSON for AI consumption.
"""

__all__ = ["check_api_coverage"]
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from scripts.mcp.tools.helpers.log_suppressor import suppress_logs
except ImportError:
    # Fallback if not available (standalone mode)
    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def suppress_logs() -> Iterator[None]:  # type: ignore[no-redef]
        yield


# Project root
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

# Import with logging suppressed
with suppress_logs():
    from nomarr.interfaces.api.api_app import api_app


def get_backend_routes() -> list[tuple[str, str]]:
    """Get all routes from FastAPI application.

    Returns:
        List of (method, path) tuples

    """
    routes = [
        (method, getattr(route, "path", ""))
        for route in api_app.routes
        if hasattr(route, "methods") and hasattr(route, "path")
        for method in sorted(getattr(route, "methods", set()))
        if method != "OPTIONS"
    ]

    return sorted(routes, key=lambda x: (x[1], x[0]))


def scan_frontend_usage(frontend_dir: Path) -> tuple[dict[str, list[tuple[str, int]]], list[str]]:
    """Scan frontend TypeScript files for API endpoint usage.

    Returns:
        Tuple of (usage_map, errors) where:
        - usage_map: Dict mapping endpoint patterns to list of (file_path, line_number) tuples
        - errors: List of error messages for files that couldn't be scanned

    """
    usage_map: dict[str, list[tuple[str, int]]] = defaultdict(list)
    errors: list[str] = []

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

        except (UnicodeDecodeError, OSError) as e:
            rel_path = ts_file.relative_to(ROOT).as_posix()
            errors.append(f"{rel_path}: {type(e).__name__}: {e}")

    return dict(usage_map), errors


def normalize_path(path: str) -> str:
    """Normalize FastAPI path params like {library_id} to {param}."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


def check_api_coverage(filter_mode: str | None = None, route_path: str | None = None) -> dict[str, Any]:
    """Check API coverage between backend and frontend.

    Args:
        filter_mode: "used", "unused", or None for all
        route_path: Filter to specific route path (e.g., "/api/web/libraries")

    Returns:
        Dict with endpoints, stats, and usage information

    """
    backend_routes = get_backend_routes()
    frontend_dir = ROOT / "frontend" / "src"
    frontend_usage, scan_errors = scan_frontend_usage(frontend_dir)

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
            },
        )

    # Calculate stats
    total = len(results)
    used_count = sum(1 for r in results if r["used"])
    unused_count = total - used_count
    coverage_pct = (used_count / total * 100) if total > 0 else 0

    result: dict[str, Any] = {
        "stats": {"total": total, "used": used_count, "unused": unused_count, "coverage_pct": round(coverage_pct, 1)},
        "endpoints": results,
    }

    if scan_errors:
        result["scan_errors"] = scan_errors

    return result
