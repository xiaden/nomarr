"""
Configuration loading and module resolution utilities.
"""

import json
import sys
from pathlib import Path
from typing import Any


def get_config_paths(script_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """
    Compute standard paths relative to the script location.

    Args:
        script_path: Path to the main script

    Returns:
        Tuple of (PROJECT_ROOT, NOMARR_PACKAGE, TESTS_PACKAGE, OUTPUTS_DIR, CONFIG_FILE)
    """
    project_root = script_path.parent.parent
    nomarr_package = project_root / "nomarr"
    tests_package = project_root / "tests"
    outputs_dir = script_path.parent / "outputs"
    config_file = script_path.parent / "configs" / "dataclass_classifier.json"
    return project_root, nomarr_package, tests_package, outputs_dir, config_file


def load_config(config_file: Path) -> dict[str, Any]:
    """
    Load configuration from scripts/configs/dataclass_classifier.json.

    If the file is missing or invalid, returns a reasonable default config.

    Args:
        config_file: Path to the config JSON file

    Returns:
        Dict with keys: layer_map, domain_map, allowed_imports, ignore_prefixes
    """
    default_config = {
        "layer_map": {
            "nomarr.interfaces": "interfaces",
            "nomarr.services": "services",
            "nomarr.app": "services",
            "nomarr.workflows": "workflows",
            "nomarr.components": "components",
            "nomarr.persistence": "persistence",
            "nomarr.helpers": "helpers",
            "tests": "tests",
        },
        "domain_map": {},
        "allowed_imports": [],
        "ignore_prefixes": [],
    }

    if not config_file.exists():
        print(f"Config file not found at {config_file}, using defaults", file=sys.stderr)
        return default_config

    try:
        config_data = json.loads(config_file.read_text(encoding="utf-8"))
        # Merge with defaults to ensure all keys exist
        result = default_config.copy()
        result.update(config_data)
        return result
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not load config from {config_file}: {e}", file=sys.stderr)
        print("Falling back to default configuration", file=sys.stderr)
        return default_config


def resolve_layer(module_path: str, layer_map: dict[str, str]) -> str:
    """
    Resolve the layer name for a module using the configured layer_map.

    Chooses the longest matching prefix from layer_map.

    Args:
        module_path: Full module path (e.g., "nomarr.services.config")
        layer_map: Dict mapping module prefixes to layer names

    Returns:
        Layer name (e.g., "services", "workflows", "helpers", "unknown")
    """
    best_match = ""
    best_layer = "unknown"

    for prefix, layer in layer_map.items():
        if module_path.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_layer = layer

    return best_layer


def resolve_domain(module_path: str, domain_map: dict[str, str]) -> str:
    """
    Resolve the domain name for a module using the configured domain_map.

    Chooses the longest matching prefix from domain_map.

    Args:
        module_path: Full module path (e.g., "nomarr.workflows.navidrome")
        domain_map: Dict mapping module prefixes to domain names

    Returns:
        Domain name (e.g., "navidrome", "processing", "unknown")
    """
    best_match = ""
    best_domain = "unknown"

    for prefix, domain in domain_map.items():
        if module_path.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_domain = domain

    return best_domain


def is_ignored_module(module_path: str, ignore_prefixes: list[str]) -> bool:
    """
    Check if a module should be ignored based on ignore_prefixes config.

    Args:
        module_path: Full module path (e.g., "tests.unit.test_foo")
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        True if module should be ignored, False otherwise
    """
    return any(module_path == prefix or module_path.startswith(prefix + ".") for prefix in ignore_prefixes)
