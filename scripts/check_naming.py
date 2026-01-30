#!/usr/bin/env python3
"""Check for naming convention violations in the codebase.

This script finds common naming anti-patterns that violate our standards.
Rules are loaded from scripts/configs/naming_rules.yaml.

Usage:
    python scripts/check_naming.py [--format=text|json] [--path=.]

Examples:
    python scripts/check_naming.py                    # Human-readable output
    python scripts/check_naming.py --format=json     # Machine-readable JSON
    python scripts/check_naming.py --path=nomarr/    # Check specific directory

"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def load_naming_rules(config_path: Path) -> dict[str, Any]:
    """Load naming rules from YAML config file."""
    try:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except FileNotFoundError:
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in config file: {e}", file=sys.stderr)
        sys.exit(1)


def should_exclude(file_path: Path, exclude_prefixes: list[str], exclude_extensions: list[str]) -> bool:
    """Check if file should be excluded from checks using simple prefix/extension matching."""
    path_str = str(file_path).replace("\\", "/")

    # Check prefix exclusions
    if any(prefix in path_str for prefix in exclude_prefixes):
        return True

    # Check extension exclusions
    return any(path_str.endswith(ext) for ext in exclude_extensions)


def check_file(
    file_path: Path, rules: list[dict[str, str]], exclude_prefixes: list[str], exclude_extensions: list[str],
) -> list[dict[str, Any]]:
    """Check a single file for naming violations.

    Returns list of violations with file, line, pattern, fix, description, and text.
    """
    if should_exclude(file_path, exclude_prefixes, exclude_extensions):
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return []

    violations: list[dict[str, Any]] = []
    lines = content.splitlines()

    for line_num, line in enumerate(lines, start=1):
        for rule in rules:
            pattern = rule["pattern"]
            fix = rule["fix"]
            description = rule["description"]

            if re.search(pattern, line):
                violations.append(
                    {
                        "file": str(file_path),
                        "line": line_num,
                        "pattern": pattern,
                        "fix": fix,
                        "description": description,
                        "text": line.strip(),
                    },
                )

    return violations


def find_python_files(root: Path, exclude_prefixes: list[str], exclude_extensions: list[str]) -> list[Path]:
    """Find all Python files in the repository or return single file if root is a file."""
    # If root is a file, return it directly (if it's a Python file)
    if root.is_file():
        if root.suffix == ".py" and not should_exclude(root, exclude_prefixes, exclude_extensions):
            return [root]
        return []

    # If root is a directory, search recursively
    return [p for p in root.rglob("*.py") if not should_exclude(p, exclude_prefixes, exclude_extensions)]


def output_text(violations: list[dict[str, Any]]) -> None:
    """Output violations in human-readable format."""
    if not violations:
        print("[OK] No naming violations found!")
        return

    print(f"[FAIL] Found {len(violations)} naming violations:\n")

    # Group by file
    by_file: dict[str, list[dict[str, Any]]] = {}
    for v in violations:
        file = v["file"]
        if file not in by_file:
            by_file[file] = []
        by_file[file].append(v)

    for file, file_violations in sorted(by_file.items()):
        print(f"FILE: {file}")
        for v in file_violations:
            print(f"   Line {v['line']:4d}: {v['description']}")
            print(f"             {v['text'][:80]}")
        print()

    print("\nSummary by pattern:")
    pattern_counts: dict[str, int] = {}
    for v in violations:
        desc = v["description"]
        pattern_counts[desc] = pattern_counts.get(desc, 0) + 1

    for desc, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"   {count:3d}x {desc}")

    print("\nTo fix: Review docs/NAMING_STANDARDS.md and update code manually")


def output_json(violations: list[dict[str, Any]]) -> None:
    """Output violations in machine-readable JSON format."""
    print(json.dumps(violations, indent=2))


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check naming conventions")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (human-readable) or json (machine-readable)",
    )
    parser.add_argument("--path", default=".", help="Root path to check (default: current directory)")

    args = parser.parse_args()
    root = Path(args.path).resolve()

    # Resolve config path relative to this script
    script_dir = Path(__file__).parent
    config_path = script_dir / "configs" / "naming_rules.yaml"

    # Load naming rules from config
    config = load_naming_rules(config_path)
    rules = config.get("rules", [])
    exclude_prefixes = config.get("exclude", [])
    exclude_extensions = config.get("exclude_extensions", [])

    if args.format == "text":
        print(f"[CHECK] Checking naming conventions in {root}")
        print(f"        Config: {config_path.relative_to(Path.cwd())}")
        print(f"        Patterns: {len(rules)} rules")
        print()

    # Find all Python files
    py_files = find_python_files(root, exclude_prefixes, exclude_extensions)

    if args.format == "text":
        print(f"[SCAN] Found {len(py_files)} Python files")
        print()

    # Check each file
    all_violations: list[dict[str, Any]] = []
    for py_file in py_files:
        violations = check_file(py_file, rules, exclude_prefixes, exclude_extensions)
        all_violations.extend(violations)

    # Output results
    if args.format == "json":
        output_json(all_violations)
    else:
        output_text(all_violations)

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
