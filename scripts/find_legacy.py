#!/usr/bin/env python3
"""
Find all references to "legacy" or "backwards compatibility" in the codebase.

Pre-alpha software should NOT have legacy code or backwards compatibility layers.
This script helps identify and remove such technical debt before it accumulates.

Usage:
    python scripts/find_legacy.py
    python scripts/find_legacy.py --format=json
    python scripts/find_legacy.py nomarr/services tests/unit
"""

import argparse
import json
import re
from pathlib import Path

# Patterns that indicate legacy/backwards compatibility code
LEGACY_PATTERNS = [
    (r"\blegacy\b", "legacy", "Code/comments mentioning 'legacy'"),
    (r"\bbackward[s]?\s+compat(?:ibility)?\b", "backwards_compat", "Backwards compatibility references"),
    (r"\bfor\s+backward[s]?\s+compat(?:ibility)?\b", "for_compat", "'For backwards compatibility' comments"),
    (r"\bdeprecated\b", "deprecated", "Deprecated code that should be removed"),
    (r"\bTODO.*remove\b", "todo_remove", "TODO comments about removing code"),
    (r"\bFIXME.*remove\b", "fixme_remove", "FIXME comments about removing code"),
]

# Directories to search
SEARCH_DIRS = [
    "nomarr",
    "tests",
]

# Files to exclude
EXCLUDE_PATTERNS = [
    r"__pycache__",
    r"\.pyc$",
    r"\.git",
    r"scripts/find_legacy\.py",  # Exclude this script
]


def should_exclude(path: Path) -> bool:
    """Check if path should be excluded."""
    path_str = str(path)
    return any(re.search(pattern, path_str) for pattern in EXCLUDE_PATTERNS)


def find_legacy_references(search_paths: list[str] | None = None):
    """
    Find all legacy references in the codebase.

    Args:
        search_paths: Optional list of paths to search. If None, uses default SEARCH_DIRS.

    Returns:
        List of violation dicts with keys: file, line, pattern, description, content
    """
    if search_paths is None:
        search_paths = SEARCH_DIRS

    violations = []

    for search_dir in search_paths:
        search_path = Path(search_dir)
        if not search_path.exists():
            continue

        for file_path in search_path.rglob("*.py"):
            if should_exclude(file_path):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                for line_num, line in enumerate(lines, start=1):
                    for pattern, pattern_name, description in LEGACY_PATTERNS:
                        if re.search(pattern, line, re.IGNORECASE):
                            violations.append(
                                {
                                    "file": str(file_path),
                                    "line": line_num,
                                    "pattern": pattern_name,
                                    "description": description,
                                    "content": line.strip(),
                                }
                            )

            except Exception as e:
                print(f"[!] Error reading {file_path}: {e}")

    return violations


def format_text_output(violations: list[dict]) -> str:
    """Format violations as human-readable text."""
    lines = []
    lines.append("=" * 80)
    lines.append("LEGACY CODE DETECTOR")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Searching for legacy/backwards compatibility references...")
    lines.append("")

    if not violations:
        lines.append("[OK] No legacy code references found!")
        return "\n".join(lines)

    # Group by file
    files_with_violations: dict[str, list[dict]] = {}
    for violation in violations:
        file_path = violation["file"]
        if file_path not in files_with_violations:
            files_with_violations[file_path] = []
        files_with_violations[file_path].append(violation)

    lines.append(f"[!] Found {len(violations)} legacy references in {len(files_with_violations)} files:")
    lines.append("")

    for file_path in sorted(files_with_violations.keys()):
        lines.append(f"File: {file_path}")
        for violation in files_with_violations[file_path]:
            lines.append(f"   Line {violation['line']:4d}: [{violation['pattern']}] {violation['content']}")
        lines.append("")

    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Total violations: {len(violations)}")
    lines.append(f"Files affected: {len(files_with_violations)}")
    lines.append("")
    lines.append("[!] PRE-ALPHA SOFTWARE SHOULD NOT HAVE LEGACY CODE!")
    lines.append("    Remove all legacy endpoints, backwards compatibility layers,")
    lines.append("    and deprecated code before accumulating technical debt.")
    lines.append("")

    return "\n".join(lines)


def format_json_output(violations: list[dict]) -> str:
    """Format violations as JSON."""
    # Count violations by pattern
    by_pattern: dict[str, int] = {}
    for violation in violations:
        pattern = violation["pattern"]
        by_pattern[pattern] = by_pattern.get(pattern, 0) + 1

    # Count unique files
    unique_files = len({v["file"] for v in violations})

    output = {
        "violations": violations,
        "summary": {
            "total_violations": len(violations),
            "files_affected": unique_files,
            "by_pattern": by_pattern,
        },
    }

    return json.dumps(output, indent=2)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Find legacy/backwards compatibility references in the codebase")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional paths to search (default: nomarr and tests)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format: text (human-readable) or json (machine-readable)",
    )

    args = parser.parse_args()

    # Use provided paths or default to SEARCH_DIRS
    search_paths = args.paths if args.paths else None

    violations = find_legacy_references(search_paths)

    # Output based on format
    if args.format == "json":
        print(format_json_output(violations))
    else:
        print(format_text_output(violations))

    # Return exit code based on violations
    return 1 if violations else 0


if __name__ == "__main__":
    exit(main())
