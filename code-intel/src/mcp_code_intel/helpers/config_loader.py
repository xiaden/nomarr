"""Configuration loader for MCP DevTools.

Loads and validates configuration from various sources with smart defaults.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default configuration matching FastAPI + React patterns
DEFAULT_CONFIG: dict[str, Any] = {
    "backend": {
        "framework": "fastapi",
        "routes": {
            "decorators": [
                "@router.get",
                "@router.post",
                "@router.put",
                "@router.patch",
                "@router.delete",
                "@app.get",
                "@app.post",
                "@app.put",
                "@app.patch",
                "@app.delete",
            ],
            "search_paths": ["**/*_if.py", "**/api/**/*.py"],
            "exclude_paths": ["**/test_*.py", "**/__pycache__/**"],
        },
        "modules": {
            "root_package": None,  # Auto-detect
            "search_paths": ["**/*.py"],
        },
        "dependency_injection": {
            "patterns": ["Depends(", "Annotated["],
            "resolver_functions": ["get_", "resolve_"],
        },
    },
    "frontend": {
        "framework": "react",
        "api_calls": {
            "patterns": [
                "api.get(",
                "api.post(",
                "api.put(",
                "api.patch(",
                "api.delete(",
                "fetch(",
                "axios.get(",
                "axios.post(",
            ],
            "search_paths": ["src/**/*.{ts,tsx,js,jsx}", "**/*.vue", "**/*.svelte"],
            "exclude_paths": ["**/node_modules/**", "**/dist/**", "**/build/**"],
        },
    },
    "project": {
        "workspace_root": ".",
        "backend_path": None,  # Auto-detect
        "frontend_path": None,  # Auto-detect
        "ignore_patterns": [
            "**/__pycache__/**",
            "**/node_modules/**",
            "**/.venv/**",
            "**/venv/**",
            "**/.git/**",
            "**/dist/**",
            "**/build/**",
        ],
    },
    "tracing": {
        "max_depth": 10,
        "filter_external": True,
        "include_patterns": [],  # Auto-detect from root_package
    },
    "tools": {
        "disabled": [],
        "custom": {},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries.

    Override values replace base values. Lists are replaced entirely (not merged).

    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def _find_config_file(workspace_root: Path) -> Path | None:
    """Find config file in workspace.

    Search order:
    1. mcp_config.json
    2. .mcp/config.json
    3. pyproject.toml [tool.mcp] (TODO)

    """
    candidates = [
        workspace_root / "mcp_config.json",
        workspace_root / ".mcp" / "config.json",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def _load_config_file(config_path: Path) -> dict[str, Any]:
    """Load and parse config file."""
    try:
        with config_path.open(encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
            return result
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in config file {config_path}: {e}"
        raise ValueError(msg) from e
    except OSError as e:
        msg = f"Failed to read config file {config_path}: {e}"
        raise ValueError(msg) from e


def _validate_config(config: dict) -> list[str]:
    """Validate config against expected structure.

    Returns list of warning messages (empty if valid).

    """
    warnings = []

    # Check for unknown top-level keys
    known_keys = {"backend", "frontend", "project", "tracing", "tools", "$schema"}
    unknown = set(config.keys()) - known_keys
    if unknown:
        warnings.append(f"Unknown config keys: {', '.join(unknown)}")

    # Validate required structure
    if "backend" in config and not isinstance(config["backend"], dict):
        warnings.append("'backend' must be an object")

    if "frontend" in config and not isinstance(config["frontend"], dict):
        warnings.append("'frontend' must be an object")

    if "tracing" in config:
        max_depth = config["tracing"].get("max_depth")
        if max_depth is not None and (not isinstance(max_depth, int) or max_depth < 1):
            warnings.append("'tracing.max_depth' must be a positive integer")

    return warnings


def _detect_backend_path(workspace_root: Path) -> str | None:
    """Detect backend path by looking for Python files."""
    candidates: list[str | Path] = ["src", "app", "backend", workspace_root]
    for candidate in candidates:
        path: Path = workspace_root / candidate if isinstance(candidate, str) else candidate
        if (path / "__init__.py").exists() or list(path.glob("**/*.py")):
            return str(path.relative_to(workspace_root))
    return None


def _detect_frontend_path(workspace_root: Path) -> str | None:
    """Detect frontend path by looking for package.json."""
    for candidate in ["frontend", "client", "web", "ui"]:
        path = workspace_root / candidate
        if (path / "package.json").exists():
            return candidate
    return None


def _detect_root_package(workspace_root: Path, backend_path: str | None) -> str | None:
    """Detect root package by finding top-level __init__.py."""
    backend_dir = workspace_root / (backend_path or ".")
    if not backend_dir.exists():
        return None

    for item in backend_dir.iterdir():
        if item.is_dir() and (item / "__init__.py").exists():
            return item.name
    return None


def _auto_detect_paths(workspace_root: Path, config: dict) -> dict:
    """Auto-detect common paths if not configured."""
    config = config.copy()

    # Auto-detect backend path
    if config["project"]["backend_path"] is None:
        config["project"]["backend_path"] = _detect_backend_path(workspace_root)

    # Auto-detect frontend path
    if config["project"]["frontend_path"] is None:
        config["project"]["frontend_path"] = _detect_frontend_path(workspace_root)

    # Auto-detect root package
    if config["backend"]["modules"]["root_package"] is None:
        backend_path = config["project"].get("backend_path")
        config["backend"]["modules"]["root_package"] = _detect_root_package(
            workspace_root,
            backend_path,
        )

    # Auto-populate tracing patterns from root_package
    root_pkg = config["backend"]["modules"]["root_package"]
    if root_pkg and not config["tracing"]["include_patterns"]:
        config["tracing"]["include_patterns"] = [f"{root_pkg}.*"]

    return config


def load_config(workspace_root: Path | None = None) -> dict:
    """Load configuration with smart defaults.

    Args:
        workspace_root: Path to workspace root (defaults to current directory)

    Returns:
        Merged configuration dict

    Raises:
        ValueError: If config file is invalid

    """
    if workspace_root is None:
        workspace_root = Path.cwd()

    # Start with defaults
    config = DEFAULT_CONFIG.copy()

    # Find and load user config
    config_path = _find_config_file(workspace_root)
    if config_path:
        user_config = _load_config_file(config_path)

        # Validate
        warnings = _validate_config(user_config)
        if warnings:
            logger.warning("Config warnings from %s:", config_path)
            for warning in warnings:
                logger.warning("  - %s", warning)

        # Merge with defaults
        config = _deep_merge(config, user_config)

    # Auto-detect missing paths
    return _auto_detect_paths(workspace_root, config)


def get_backend_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract backend-specific config."""
    result: dict[str, Any] = config.get("backend", DEFAULT_CONFIG["backend"])
    return result


def get_frontend_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract frontend-specific config."""
    result: dict[str, Any] = config.get("frontend", DEFAULT_CONFIG["frontend"])
    return result


def get_tracing_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract tracing-specific config."""
    result: dict[str, Any] = config.get("tracing", DEFAULT_CONFIG["tracing"])
    return result


def is_tool_disabled(config: dict, tool_name: str) -> bool:
    """Check if a tool is disabled in config."""
    disabled = config.get("tools", {}).get("disabled", [])
    return tool_name in disabled


def get_workspace_root() -> Path:
    """Get workspace root by finding pyproject.toml or .git."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    return current


def get_python_search_paths(
    config: dict | None = None, workspace_root: Path | None = None
) -> list[Path]:
    """Get list of Python directories to search for symbols.

    Uses config's backend.modules.search_paths if available, otherwise
    auto-detects Python packages in workspace root.

    Returns:
        List of absolute paths to search for Python files.

    """
    if workspace_root is None:
        workspace_root = get_workspace_root()

    if config is None:
        config = load_config(workspace_root)

    search_paths: list[Path] = []

    # Get configured search paths or use defaults
    backend_config = get_backend_config(config)
    patterns = backend_config.get("modules", {}).get("search_paths", ["**/*.py"])

    # Convert glob patterns to actual directories
    for pattern in patterns:
        # For patterns like "nomarr/**/*.py", extract the root directory
        if "**" in pattern:
            root_part = pattern.split("**")[0].rstrip("/")
            if root_part:
                path = workspace_root / root_part
                if path.exists() and path.is_dir():
                    search_paths.append(path)
        else:
            # Direct path pattern
            for match in workspace_root.glob(pattern):
                if match.is_dir():
                    search_paths.append(match)
                elif match.is_file() and match.parent not in search_paths:
                    search_paths.append(match.parent)

    # If no paths found, auto-detect Python packages
    if not search_paths:
        for item in workspace_root.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                search_paths.append(item)

    return search_paths


def get_root_package(config: dict | None = None, workspace_root: Path | None = None) -> str | None:
    """Get the root package name from config or auto-detect.

    Returns:
        Root package name (e.g., 'nomarr', 'myapp') or None if not found.

    """
    if workspace_root is None:
        workspace_root = get_workspace_root()

    if config is None:
        config = load_config(workspace_root)

    backend_config = get_backend_config(config)
    modules: dict[str, Any] = backend_config.get("modules", {})
    root_pkg: str | None = modules.get("root_package")
    return root_pkg


def resolve_module_path(module_name: str, workspace_root: Path | None = None) -> Path | None:
    """Resolve a module name to its file path.

    Searches in workspace root and configured search paths.

    Args:
        module_name: Dotted module name (e.g., 'nomarr.services.config_svc')
        workspace_root: Workspace root directory

    Returns:
        Path to the module file, or None if not found.

    """
    if workspace_root is None:
        workspace_root = get_workspace_root()

    parts = module_name.split(".")

    # List of base directories to search
    search_bases = [workspace_root]

    # Also search in configured search paths
    try:
        config = load_config(workspace_root)
        for search_path in get_python_search_paths(config, workspace_root):
            # For paths like code-intel/src/mcp_code_intel, add the parent
            # so we can resolve mcp_code_intel.helpers.plan_md
            if search_path.name == parts[0]:
                search_bases.append(search_path.parent)
            else:
                search_bases.append(search_path)
    except Exception:
        pass  # Fall back to just workspace root

    for base in search_bases:
        # Try as a direct module file
        module_path = base / Path(*parts).with_suffix(".py")
        if module_path.exists():
            return module_path

        # Try as a package __init__.py
        package_path = base / Path(*parts) / "__init__.py"
        if package_path.exists():
            return package_path

    return None
