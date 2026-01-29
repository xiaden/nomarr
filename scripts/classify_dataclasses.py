#!/usr/bin/env python3
"""Classify @dataclass definitions in Nomarr codebase.

This is a thin CLI wrapper around the dataclass_classifier toolkit.
All logic lives in scripts/tools/dataclass_classifier/ modules.
"""

import argparse
import sys
from pathlib import Path

# Add tools directory to path for imports
SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent / "tools"))

from dataclass_classifier import (  # type: ignore  # noqa: E402
    analyze_usage,
    classify_all,
    detect_suspect_imports,
    discover_all_dataclasses,
    discover_missing_dataclasses,
    get_config_paths,
    load_config,
    write_json_output,
    write_text_output,
)


def main() -> int:
    """Main entry point for the script.

    Returns:
        Exit code (0 for success)

    """
    parser = argparse.ArgumentParser(
        description="Classify dataclasses in Nomarr codebase according to architecture rules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/classify_dataclasses.py
  python scripts/classify_dataclasses.py --format=json

Output files are written to scripts/outputs/:
  - scripts/outputs/dataclasses.txt (text format)
  - scripts/outputs/dataclasses.json (JSON format)
        """,
    )

    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (human-readable) or json (machine-readable)",
    )

    args = parser.parse_args()

    # Get standard paths relative to script location
    outputs_dir, config_file, script_dir = get_config_paths(SCRIPT_PATH)

    # Load configuration
    print("Loading configuration...")
    config = load_config(config_file)
    layer_map = config["layer_map"]
    domain_map = config["domain_map"]
    allowed_imports = config["allowed_imports"]
    ignore_prefixes = config.get("ignore_prefixes", [])

    # Resolve project_root from config (relative to script_dir)
    project_root_config = config.get("project_root", "../..")
    project_root = Path(project_root_config)
    if not project_root.is_absolute():
        project_root = (script_dir / project_root).resolve()

    if not project_root.exists():
        print(
            f"Error: Configured project_root '{project_root_config}' resolves to {project_root} which does not exist",
            file=sys.stderr,
        )
        return 1

    # Resolve search_paths from config (relative to project_root)
    search_paths_config = config.get("search_paths", ["nomarr"])
    search_paths = []
    for path_str in search_paths_config:
        search_path = Path(path_str)
        if not search_path.is_absolute():
            search_path = (project_root / search_path).resolve()

        if search_path.exists():
            search_paths.append(search_path)
        else:
            print(
                f"Warning: Search path '{path_str}' resolves to {search_path} which does not exist, skipping",
                file=sys.stderr,
            )

    if not search_paths:
        print("Error: No valid search paths configured", file=sys.stderr)
        return 1

    print(f"Project root: {project_root}")
    print(f"Searching in: {', '.join(str(p.relative_to(project_root)) for p in search_paths)}")

    # Discover all dataclasses
    print("Discovering dataclasses...")
    dataclasses = discover_all_dataclasses(project_root, search_paths, layer_map, domain_map, ignore_prefixes)
    print(f"Found {len(dataclasses)} dataclasses")

    # Analyze usage patterns
    print("Analyzing usage patterns...")
    import_edges = analyze_usage(project_root, search_paths, dataclasses, layer_map, domain_map, ignore_prefixes)

    # Classify dataclasses
    print("Classifying dataclasses...")
    classify_all(dataclasses)

    # Detect suspect imports
    print("Detecting suspect imports...")
    suspect_imports = detect_suspect_imports(import_edges, allowed_imports, ignore_prefixes)
    if suspect_imports:
        print(f"Found {len(suspect_imports)} suspect import(s)")
    else:
        print("No suspect imports found (or allowed_imports not configured)")

    # Discover missing dataclass candidates
    print("Discovering missing dataclass candidates...")
    missing_candidates = discover_missing_dataclasses(
        project_root, search_paths, layer_map, domain_map, ignore_prefixes
    )
    if missing_candidates:
        print(f"Found {len(missing_candidates)} candidate(s)")
    else:
        print("No missing dataclass candidates found")

    # Ensure output directory exists
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Write output based on format
    if args.format == "json":
        output_path = outputs_dir / "dataclasses.json"
        write_json_output(dataclasses, suspect_imports, missing_candidates, output_path, project_root)
    else:
        output_path = outputs_dir / "dataclasses.txt"
        write_text_output(dataclasses, suspect_imports, missing_candidates, output_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
