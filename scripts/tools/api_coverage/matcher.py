"""Match backend routes to frontend usage."""

import re

from .models import EndpointUsage


def normalize_path_params(path: str) -> str:
    """Convert FastAPI path params {id} to generic pattern."""
    return re.sub(r"\{[^}]+\}", "{param}", path)


def match_endpoint_usage(
    backend_routes: list[tuple[str, str, str | None, str | None, str | None, int | None]],
    frontend_usage: dict[str, list[tuple[str, int]]],
) -> list[EndpointUsage]:
    """
    Match backend routes to frontend usage.

    Args:
        backend_routes: List of (method, path, summary, description, file_path, line_number)
        frontend_usage: Dict of endpoint -> [(file, line)]

    Returns:
        List of EndpointUsage objects
    """
    endpoint_usages = []

    for method, path, summary, description, backend_file, backend_line in backend_routes:
        normalized = normalize_path_params(path)

        # Check if this endpoint is used
        frontend_files = []
        for frontend_path in frontend_usage:
            # Try exact match first
            if frontend_path == path:
                frontend_files.extend(frontend_usage[frontend_path])
            # Try normalized match (for path params)
            elif normalize_path_params(frontend_path) == normalized:
                frontend_files.extend(frontend_usage[frontend_path])

        used = len(frontend_files) > 0
        endpoint_usages.append(
            EndpointUsage(
                method=method,
                path=path,
                used=used,
                frontend_files=frontend_files,
                summary=summary,
                description=description,
                backend_file=backend_file,
                backend_line=backend_line,
            )
        )

    return endpoint_usages
