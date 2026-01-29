"""Configuration loading for code graph builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Resolve script path for config loading
SCRIPT_PATH = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT_PATH.parent.parent.parent  # scripts/tools/build_code_graph -> scripts
CONFIG_FILE = SCRIPT_DIR / "configs" / "code_graph_config.json"


def load_config() -> dict[str, Any]:
    """Load configuration from JSON file."""
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)

    with CONFIG_FILE.open("r", encoding="utf-8") as f:
        config: dict[str, Any] = json.load(f)

    return config


def resolve_paths(config: dict[str, Any]) -> tuple[Path, list[Path], Path]:
    """Resolve project root, search paths, and output path from config.

    Returns:
        (project_root, search_paths, output_path)

    """
    # Resolve project_root (relative to script directory)
    project_root_str = config.get("project_root", "..")
    project_root = Path(project_root_str)
    if not project_root.is_absolute():
        project_root = (SCRIPT_DIR / project_root).resolve()

    if not project_root.exists():
        print(f"Error: project_root does not exist: {project_root}", file=sys.stderr)
        sys.exit(1)

    # Resolve search_paths (relative to project_root)
    search_paths_config = config.get("search_paths", ["nomarr"])
    search_paths = []
    for path_str in search_paths_config:
        search_path = Path(path_str)
        if not search_path.is_absolute():
            search_path = (project_root / search_path).resolve()

        if search_path.exists():
            search_paths.append(search_path)
        else:
            print(f"Warning: Search path does not exist, skipping: {search_path}", file=sys.stderr)

    if not search_paths:
        print("Error: No valid search paths found", file=sys.stderr)
        sys.exit(1)

    # Resolve output_path (relative to script directory)
    output_path_str = config.get("output_path", "scripts/outputs/code_graph.json")
    output_path = Path(output_path_str)
    if not output_path.is_absolute():
        output_path = (SCRIPT_DIR / output_path).resolve()

    return project_root, search_paths, output_path
