"""ML-optimized API coverage checker.

Checks which backend API endpoints are used by the frontend.
Returns structured JSON for AI consumption.

Uses static AST parsing via helpers/route_parser.py - no app import required.
"""

__all__ = ["project_check_api_coverage"]
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.mcp.tools.helpers.config_loader import (
    get_frontend_config,
    load_config,
)
from scripts.mcp.tools.helpers.route_parser import build_full_paths, parse_interface_files

# Project root
ROOT = Path(__file__).parent.parent.parent.parent


def _build_endpoint_patterns(api_call_config: dict) -> tuple[re.Pattern, re.Pattern]:
    """Build regex patterns for endpoint detection from config.

    Args:
        api_call_config: Frontend API call configuration from config

    Returns:
        Tuple of (endpoint_pattern, template_pattern)

    """
    # Default: look for /api/ endpoints in strings and templates
    endpoint_pattern = re.compile(r"""[\"'`](/api/[^\"'`\s]+)[\"'`]""")
    template_pattern = re.compile(r"`(/api/[^`]+)`")

    return endpoint_pattern, template_pattern


def get_backend_routes(project_root: Path | None = None) -> list[tuple[str, str]]:
    """Get all routes from static AST analysis.

    Args:
        project_root: Path to project root. Defaults to ROOT constant.

    Returns:
        List of (method, path) tuples

    """
    if project_root is None:
        project_root = ROOT

    interfaces_dir = project_root / "nomarr" / "interfaces" / "api"
    if not interfaces_dir.exists():
        return []

    routers = parse_interface_files(interfaces_dir)
    routes_data = build_full_paths(routers, project_root)

    routes = [(route["method"], route["path"]) for route in routes_data if route.get("method") != "OPTIONS"]

    return sorted(routes, key=lambda x: (x[1], x[0]))


def scan_frontend_usage(
    frontend_dir: Path,
    file_extensions: list[str] | None = None,
    endpoint_pattern: re.Pattern | None = None,
    template_pattern: re.Pattern | None = None,
) -> tuple[dict[str, list[tuple[str, int]]], list[str]]:
    """Scan frontend files for API endpoint usage.

    Args:
        frontend_dir: Path to frontend source directory
        file_extensions: List of file extensions to scan (default: [\"ts\"])
        endpoint_pattern: Regex pattern for endpoint strings (default: /api/...)
        template_pattern: Regex pattern for template literals (default: `/api/...`)

    Returns:
        Tuple of (usage_map, errors) where:
        - usage_map: Dict mapping endpoint patterns to list of (file_path, line_number) tuples
        - errors: List of error messages for files that couldn't be scanned

    """
    if file_extensions is None:
        file_extensions = ["ts"]
    if endpoint_pattern is None:
        endpoint_pattern = re.compile(r"""[\"'`](/api/[^\"'`\s]+)[\"'`]""")
    if template_pattern is None:
        template_pattern = re.compile(r"`(/api/[^`]+)`")

    usage_map: dict[str, list[tuple[str, int]]] = defaultdict(list)
    errors: list[str] = []

    # Build glob patterns from file extensions
    glob_patterns = [f"*.{ext}" for ext in file_extensions]

    for glob_pattern in glob_patterns:
        for ts_file in frontend_dir.rglob(glob_pattern):
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


def project_check_api_coverage(filter_mode: str | None = None, route_path: str | None = None, config: dict | None = None) -> dict[str, Any]:
    """Check API coverage between backend and frontend.

    Analyzes which backend API endpoints are actually used by frontend code.
    Uses configuration to determine frontend source paths and API call patterns.

    Configuration used:
        frontend.api_calls.patterns: List of API call patterns to match
            Example: ["api.get", "api.post", "fetch(", "axios.get"]
            Default: ["api.get", "api.post", "api.put", "api.delete", "fetch(", "axios.get"]
        frontend.api_calls.search_paths: Directories to scan for frontend code
            Example: ["src", "components", "pages"]
            Default: ["src"]

    Args:
        filter_mode: "used", "unused", or None for all
        route_path: Filter to specific route path (e.g., "/api/web/libraries")
        config: Optional config dict. If not provided, loaded from workspace.
            Can be obtained from: load_config(project_root)

    Returns:
        Dict with endpoints, stats, and usage information
            - stats: {total, used, unused, coverage_pct}
            - endpoints: [{method, path, used, usage_count, locations}]
            - scan_errors: Optional list of errors during frontend scan

    """
    # Load config if not provided (dependency injection)
    if config is None:
        config = load_config(ROOT)
    frontend_config = get_frontend_config(config)

    # Get patterns from config
    api_calls_config = frontend_config.get("api_calls", {})
    endpoint_pattern, template_pattern = _build_endpoint_patterns(api_calls_config)

    # Get routes and scan frontend
    backend_routes = get_backend_routes(ROOT)
    frontend_dir = ROOT / "frontend" / "src"
    frontend_usage, scan_errors = scan_frontend_usage(
        frontend_dir,
        file_extensions=["ts", "tsx", "js", "jsx"],
        endpoint_pattern=endpoint_pattern,
        template_pattern=template_pattern,
    )

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
