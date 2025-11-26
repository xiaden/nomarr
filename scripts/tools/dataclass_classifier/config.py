"""
Configuration loading and module resolution utilities.
"""

import json
import sys
from pathlib import Path
from typing import Any


def get_config_paths(script_path: Path) -> tuple[Path, Path, Path]:
    """
    Compute standard paths relative to the script location.

    Args:
        script_path: Path to the main script

    Returns:
        Tuple of (OUTPUTS_DIR, CONFIG_FILE, SCRIPT_DIR)
    """
    script_dir = script_path.parent
    outputs_dir = script_dir / "outputs"
    config_file = script_dir / "configs" / "dataclass_classifier.json"
    return outputs_dir, config_file, script_dir


def load_config(config_file: Path) -> dict[str, Any]:
    """
    Load configuration from scripts/configs/dataclass_classifier.json.

    If the file is missing or invalid, returns a reasonable default config.

    Args:
        config_file: Path to the config JSON file

    Returns:
        Dict with keys: project_root, search_paths, layer_map, domain_map, allowed_imports, ignore_prefixes
    """
    default_config: dict[str, Any] = {
        "project_root": "..",
        "search_paths": ["nomarr"],
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
    Resolve the layer name for a module based on its package path.

    Layer is determined purely by the top-level package structure:
    - nomarr.interfaces.* → "interfaces"
    - nomarr.services.* → "services"
    - nomarr.workflows.* → "workflows"
    - nomarr.components.* → "components"
    - nomarr.persistence.* → "persistence"
    - nomarr.helpers.* → "helpers"
    - tests.* → "tests"

    This is suffix-agnostic; layer depends only on package path.

    Args:
        module_path: Full module path (e.g., "nomarr.services.queue_svc")
        layer_map: Dict mapping module prefixes to layer names (for fallback)

    Returns:
        Layer name (e.g., "services", "workflows", "helpers", "unknown")
    """
    # Direct layer resolution based on package structure
    if module_path.startswith("nomarr.interfaces"):
        return "interfaces"
    elif module_path.startswith("nomarr.services"):
        return "services"
    elif module_path.startswith("nomarr.workflows"):
        return "workflows"
    elif module_path.startswith("nomarr.components"):
        return "components"
    elif module_path.startswith("nomarr.persistence"):
        return "persistence"
    elif module_path.startswith("nomarr.helpers"):
        return "helpers"
    elif module_path.startswith("tests"):
        return "tests"
    elif module_path.startswith("nomarr.app"):
        return "services"  # app is considered part of services

    # Fallback to layer_map for any special cases
    best_match = ""
    best_layer = "unknown"
    for prefix, layer in layer_map.items():
        if module_path.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_layer = layer

    return best_layer


def resolve_domain(module_path: str, domain_map: dict[str, str]) -> str:
    """
    Resolve the domain name for a module using suffix-aware heuristics.

    Algorithm:
    1. Identify the layer segment (services, workflows, components, etc.)
    2. Extract the layer-local path (everything after the layer segment)
    3. Determine domain from the layer-local path:
       - If there's a subpackage, use it as the domain
         (e.g., "workflows.navidrome.preview_wf" → "navidrome")
       - If the module is directly in the layer, derive from filename by stripping suffixes
         (e.g., "services.queue_svc" → "queue")
    4. Fall back to domain_map for explicit overrides
    5. Return "unknown" if no domain can be inferred

    Known suffixes stripped when inferring domain:
    _svc, _wf, _comp, _sql, _if, _cli, _dto, _types, _request_types, _helper

    Args:
        module_path: Full module path (e.g., "nomarr.services.queue_svc")
        domain_map: Dict mapping module prefixes to domain names (for overrides)

    Returns:
        Domain name (e.g., "navidrome", "queue", "analytics", "unknown")
    """
    # Known suffixes to strip when deriving domain from module name
    KNOWN_SUFFIXES = [
        "_svc",
        "_wf",
        "_comp",
        "_sql",
        "_if",
        "_cli",
        "_dto",
        "_types",
        "_request_types",
        "_helper",
    ]

    # Check domain_map first for explicit overrides
    best_match = ""
    best_domain = ""
    for prefix, domain in domain_map.items():
        if module_path.startswith(prefix) and len(prefix) > len(best_match):
            best_match = prefix
            best_domain = domain

    # If we found an explicit mapping, use it
    if best_domain:
        return best_domain

    # Parse module path into parts
    parts = module_path.split(".")

    # Find the layer segment index
    layer_idx = -1
    layer_segments = ["interfaces", "services", "workflows", "components", "persistence", "helpers"]

    for idx, part in enumerate(parts):
        if part in layer_segments:
            layer_idx = idx
            break

    # If no layer found, return unknown
    if layer_idx == -1 or layer_idx >= len(parts) - 1:
        return "unknown"

    # Extract layer-local path (everything after layer segment)
    layer_local = parts[layer_idx + 1 :]

    # Case 1: Multi-level path with subpackage (e.g., ["navidrome", "preview_wf"])
    if len(layer_local) > 1:
        # The first component is likely the domain
        domain = layer_local[0]
        # Filter out generic names
        if domain not in ["database", "api", "web", "v1", "commands", "types", "dto"]:
            return domain

    # Case 2: Single module name (e.g., ["queue_svc"])
    if len(layer_local) == 1:
        module_name = layer_local[0]

        # Strip known suffixes to derive domain
        domain = module_name
        for suffix in KNOWN_SUFFIXES:
            if domain.endswith(suffix):
                domain = domain[: -len(suffix)]
                break

        # Return derived domain if it's meaningful
        if domain and domain != module_name:
            return domain

        # For modules without known suffixes, return the module name itself as domain
        if domain:
            return domain

    # Case 3: Special handling for deeply nested paths
    # e.g., "nomarr.interfaces.api.types.queue_types" → "queue"
    # e.g., "nomarr.helpers.dto.queue_dto" → "queue"
    if len(layer_local) >= 2 and layer_local[0] in ["api", "dto", "database", "commands"]:
        # Check if the next level is another generic name
        if layer_local[1] in ["types", "web", "v1"]:
            # Use the third level if available
            if len(layer_local) >= 3:
                module_name = layer_local[2]
                domain = module_name
                for suffix in KNOWN_SUFFIXES:
                    if domain.endswith(suffix):
                        domain = domain[: -len(suffix)]
                        break
                if domain:
                    return domain
        else:
            # Use the second level
            module_name = layer_local[1]
            domain = module_name
            for suffix in KNOWN_SUFFIXES:
                if domain.endswith(suffix):
                    domain = domain[: -len(suffix)]
                    break
            if domain:
                return domain

    return "unknown"


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
