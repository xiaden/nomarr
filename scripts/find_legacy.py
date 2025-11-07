#!/usr/bin/env python3
"""
Find all references to "legacy" or "backwards compatibility" in the codebase.

Pre-alpha software should NOT have legacy code or backwards compatibility layers.
This script helps identify and remove such technical debt before it accumulates.
"""

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


def find_legacy_references():
    """Find all legacy references in the codebase."""
    violations = []

    for search_dir in SEARCH_DIRS:
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
                print(f"⚠️  Error reading {file_path}: {e}")

    return violations


def main():
    """Main entry point."""
    print("=" * 80)
    print("LEGACY CODE DETECTOR")
    print("=" * 80)
    print()
    print("Searching for legacy/backwards compatibility references...")
    print()

    violations = find_legacy_references()

    if not violations:
        print("✅ No legacy code references found!")
        return 0

    # Group by file
    files_with_violations = {}
    for violation in violations:
        file_path = violation["file"]
        if file_path not in files_with_violations:
            files_with_violations[file_path] = []
        files_with_violations[file_path].append(violation)

    print(f"❌ Found {len(violations)} legacy references in {len(files_with_violations)} files:")
    print()

    for file_path in sorted(files_with_violations.keys()):
        print(f"📄 {file_path}")
        for violation in files_with_violations[file_path]:
            print(f"   Line {violation['line']:4d}: [{violation['pattern']}] {violation['content']}")
        print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total violations: {len(violations)}")
    print(f"Files affected: {len(files_with_violations)}")
    print()
    print("⚠️  PRE-ALPHA SOFTWARE SHOULD NOT HAVE LEGACY CODE!")
    print("   Remove all legacy endpoints, backwards compatibility layers,")
    print("   and deprecated code before accumulating technical debt.")
    print()

    return 1


if __name__ == "__main__":
    exit(main())
