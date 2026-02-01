"""Discover backend routes and frontend usage."""

import re
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def get_backend_routes() -> list[tuple[str, str, str | None, str | None, str | None, int | None]]:
    """Get all routes from FastAPI application.

    Returns:
        List of (method, path, summary, description, file_path, line_number) tuples

    """
    # Ignore list: FastAPI auto-generated docs and root endpoint
    ignored_routes = {
        ("GET", "/"),
        ("GET", "/docs"),
        ("HEAD", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("HEAD", "/docs/oauth2-redirect"),
        ("GET", "/openapi.json"),
        ("HEAD", "/openapi.json"),
        ("GET", "/redoc"),
        ("HEAD", "/redoc"),
    }

    import inspect

    from nomarr.interfaces.api.api_app import api_app

    routes = []
    for route in api_app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            methods_list = getattr(route, "methods", set())
            route_path = getattr(route, "path", "")

            # Extract docstring and location from endpoint function
            summary = None
            description = None
            file_path = None
            line_number = None

            if hasattr(route, "endpoint") and route.endpoint:
                # Get docstring
                docstring = route.endpoint.__doc__
                if docstring:
                    docstring = docstring.strip()
                    lines = docstring.split("\n", 1)
                    summary = lines[0].strip()
                    if len(lines) > 1:
                        description = lines[1].strip()

                # Get file location
                try:
                    source_file = inspect.getsourcefile(route.endpoint)
                    if source_file:
                        file_path = str(Path(source_file).relative_to(project_root))
                        _, line_number = inspect.getsourcelines(route.endpoint)
                except Exception:
                    pass

            # Skip OPTIONS (auto-generated CORS) and ignored routes
            for method in sorted(methods_list):
                if method != "OPTIONS" and (method, route_path) not in ignored_routes:
                    routes.append((method, route_path, summary, description, file_path, line_number))

    return sorted(routes, key=lambda x: (x[1], x[0]))


def scan_frontend_usage(frontend_dir: Path) -> dict[str, list[tuple[str, int]]]:
    """Scan frontend TypeScript files for API endpoint usage.

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
                    endpoint = match.group(1)
                    endpoint_base = endpoint.split("?")[0]
                    rel_path = ts_file.relative_to(project_root).as_posix()
                    usage_map[endpoint_base].append((rel_path, line_num))

                for match in template_pattern.finditer(line):
                    endpoint = match.group(1)
                    endpoint_base = re.sub(r"\$\{[^}]+\}", "{param}", endpoint)
                    endpoint_base = endpoint_base.split("?")[0]
                    rel_path = ts_file.relative_to(project_root).as_posix()
                    usage_map[endpoint_base].append((rel_path, line_num))

        except Exception:
            continue

    return dict(usage_map)
