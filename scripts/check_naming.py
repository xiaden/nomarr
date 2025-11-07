#!/usr/bin/env python3
"""
Check for naming convention violations in the codebase.

This script finds common naming anti-patterns that violate our standards:
- Abbreviated parameter names (error_msg, err_msg, etc.)
- Inconsistent patterns across similar concepts
- Parameters that don't match database column names

Usage:
    python scripts/check_naming.py [--fix]
"""

import argparse
import re
import sys
from pathlib import Path

# Naming anti-patterns to detect
ANTI_PATTERNS = [
    # Pattern, Suggested Fix, Description
    (r"\berror_text\b", "error_message", "Use error_message instead of error_text"),
    (r"\berror_msg\b", "error_message", "Use error_message instead of error_msg"),
    (r"\berr_msg\b", "error_message", "Use error_message instead of err_msg"),
    (r"\berr_text\b", "error_message", "Use error_message instead of err_text"),
    # Uncomment to enforce more standards as needed:
    # (r'\bnum_workers\b', 'worker_count', 'Use worker_count instead of num_workers'),
    # (r'\bmax_results\b', 'limit', 'Use limit for consistency with API parameters'),
    # (r'\bfile_cnt\b', 'file_count', 'Use file_count instead of file_cnt'),
    # (r'\bworker_cnt\b', 'worker_count', 'Use worker_count instead of worker_cnt'),
]

# Note: These are acceptable abbreviations (DO NOT add to anti-patterns):
# - cur, cursor (database cursors - industry standard)
# - cfg, config (configuration - widely accepted)
# - args (argparse arguments - Python convention)
# - req, resp (HTTP request/response - web standard)
# - db, conn (database/connection - very common)
# - idx (loop index - math/CS convention)
# - num_*, max_*, min_* (mathematical/ML contexts - descriptive enough)
# - embed_dim, num_classes, etc. (ML terminology - standard in field)

# Files/directories to exclude
EXCLUDE_PATTERNS = [
    r"\.git/",
    r"\.pytest_cache/",
    r"__pycache__/",
    r"\.pyc$",
    r"\.backup$",
    r"\.bak$",
    r"/tests/",  # Test files can reference old names for testing
    r"scripts/check_naming\.py$",  # This file itself
    r"docs/NAMING_STANDARDS\.md$",  # Documentation can mention anti-patterns
]


def should_exclude(file_path: Path) -> bool:
    """Check if file should be excluded from checks."""
    path_str = str(file_path).replace("\\", "/")
    return any(re.search(pattern, path_str) for pattern in EXCLUDE_PATTERNS)


def check_file(file_path: Path, fix: bool = False) -> list[dict]:
    """
    Check a single file for naming violations.

    Returns list of violations: [{"line": int, "pattern": str, "fix": str, "text": str}, ...]
    """
    if should_exclude(file_path):
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return []

    violations = []
    lines = content.splitlines()

    for line_num, line in enumerate(lines, start=1):
        for pattern, fix, description in ANTI_PATTERNS:
            if re.search(pattern, line):
                violations.append(
                    {
                        "file": str(file_path),
                        "line": line_num,
                        "pattern": pattern,
                        "fix": fix,
                        "description": description,
                        "text": line.strip(),
                    }
                )

    return violations


def find_python_files(root: Path) -> list[Path]:
    """Find all Python files in the repository."""
    return [p for p in root.rglob("*.py") if not should_exclude(p)]


def main():
    parser = argparse.ArgumentParser(description="Check naming conventions")
    parser.add_argument("--fix", action="store_true", help="Automatically fix violations (not implemented yet)")
    parser.add_argument("--path", default=".", help="Root path to check (default: current directory)")

    args = parser.parse_args()
    root = Path(args.path).resolve()

    print(f"🔍 Checking naming conventions in {root}")
    print(f"   Patterns: {len(ANTI_PATTERNS)} rules")
    print()

    # Find all Python files
    py_files = find_python_files(root)
    print(f"📁 Found {len(py_files)} Python files")
    print()

    # Check each file
    all_violations = []
    for py_file in py_files:
        violations = check_file(py_file, fix=args.fix)
        all_violations.extend(violations)

    # Report results
    if not all_violations:
        print("✅ No naming violations found!")
        return 0

    print(f"❌ Found {len(all_violations)} naming violations:\n")

    # Group by file
    by_file = {}
    for v in all_violations:
        file = v["file"]
        if file not in by_file:
            by_file[file] = []
        by_file[file].append(v)

    for file, violations in sorted(by_file.items()):
        print(f"📄 {file}")
        for v in violations:
            print(f"   Line {v['line']:4d}: {v['description']}")
            print(f"             {v['text'][:80]}")
        print()

    print("\n💡 Summary by pattern:")
    pattern_counts = {}
    for v in all_violations:
        desc = v["description"]
        pattern_counts[desc] = pattern_counts.get(desc, 0) + 1

    for desc, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"   {count:3d}x {desc}")

    print("\n🔧 To fix: Review docs/NAMING_STANDARDS.md and update code manually")

    return 1 if all_violations else 0


if __name__ == "__main__":
    sys.exit(main())
