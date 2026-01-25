#!/usr/bin/env python3
"""
Check if a code migration is complete.

Validates that old patterns are fully eliminated:
- Old module/function deleted
- No imports remain
- No string references in code
- No skill references
- No TODO/DEPRECATED comments about it
- Ruff ban exists (only when --expect-ban is specified)

Usage:
    python scripts/check_migration.py nomarr.helpers.old_module
    python scripts/check_migration.py nomarr.helpers.old_module.old_function
    python scripts/check_migration.py --old nomarr.services.queue_svc --new nomarr.services.domain.tagging_svc
    python scripts/check_migration.py nomarr.services.queue_svc --format=json
    python scripts/check_migration.py nomarr.helpers.time --expect-ban  # Verify ruff ban exists
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

NOMARR_ROOT = Path("nomarr")
SKILLS_DIR = Path(".github/skills")
RUFF_TOML = Path("tool_configs/ruff.toml")


class MigrationCheckResult(TypedDict):
    """Result of migration completeness check."""

    old_pattern: str
    new_pattern: str | None
    complete: bool
    issues: list[str]
    warnings: list[str]
    details: dict[str, list[str]]


@dataclass
class MigrationChecker:
    """Check if a migration is complete."""

    old_pattern: str
    new_pattern: str | None = None
    expect_ban: bool = False
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, list[str]] = field(default_factory=dict)
    _old_code_exists: bool = field(default=False, init=False)

    def check_all(self) -> MigrationCheckResult:
        """Run all migration checks."""
        self._old_code_exists = self._check_old_code_exists()
        self.check_old_code_deleted()
        self.check_imports_removed()
        self.check_string_references()
        self.check_skill_references()
        if self.expect_ban:
            self.check_ruff_ban()
        self.check_todo_comments()

        if self.new_pattern:
            self.check_new_code_exists()

        return MigrationCheckResult(
            old_pattern=self.old_pattern,
            new_pattern=self.new_pattern,
            complete=len(self.issues) == 0,
            issues=self.issues,
            warnings=self.warnings,
            details=self.details,
        )

    def check_old_code_deleted(self) -> None:
        """Check that old module/function no longer exists."""
        if self._old_code_exists:
            # Record the issue with details
            parts = self.old_pattern.split(".")
            if parts[0] != "nomarr":
                return

            mod_path = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-1]}.py"
            if mod_path.exists():
                self.issues.append(f"Old module still exists: {mod_path}")
                return

            pkg_path = NOMARR_ROOT / "/".join(parts[1:])
            if pkg_path.is_dir() and (pkg_path / "__init__.py").exists():
                self.issues.append(f"Old package still exists: {pkg_path}")
                return

            if len(parts) >= 3:
                parent_mod = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-2]}.py"
                if not parent_mod.exists():
                    parent_mod = NOMARR_ROOT / "/".join(parts[1:-1]) / "__init__.py"
                if parent_mod.exists():
                    self.issues.append(
                        f"Old function/class '{parts[-1]}' still exists in {parent_mod}"
                    )

    def _check_old_code_exists(self) -> bool:
        """Check if old code exists (without recording issues)."""
        parts = self.old_pattern.split(".")

        if parts[0] != "nomarr":
            return False

        # Try as module file
        mod_path = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-1]}.py"
        if mod_path.exists():
            return True

        # Try as package
        pkg_path = NOMARR_ROOT / "/".join(parts[1:])
        if pkg_path.is_dir() and (pkg_path / "__init__.py").exists():
            return True

        # Try as function in module
        if len(parts) >= 3:
            parent_mod = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-2]}.py"
            if not parent_mod.exists():
                parent_mod = NOMARR_ROOT / "/".join(parts[1:-1]) / "__init__.py"

            if parent_mod.exists():
                func_name = parts[-1]
                content = parent_mod.read_text(encoding="utf-8")
                if re.search(rf"^(def|class)\s+{func_name}\b", content, re.MULTILINE):
                    return True

        return False

    def check_new_code_exists(self) -> None:
        """Check that new module/function exists (if specified)."""
        if not self.new_pattern:
            return

        parts = self.new_pattern.split(".")
        if not parts[0] == "nomarr":
            return

        # Try as module
        mod_path = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-1]}.py"
        if mod_path.exists():
            return

        # Try as package
        pkg_path = NOMARR_ROOT / "/".join(parts[1:])
        if pkg_path.is_dir() and (pkg_path / "__init__.py").exists():
            return

        # Try as function in parent module
        if len(parts) >= 3:
            parent_mod = NOMARR_ROOT / "/".join(parts[1:-1]) / f"{parts[-2]}.py"
            if parent_mod.exists():
                return

        self.warnings.append(f"New pattern location not found: {self.new_pattern}")

    def check_imports_removed(self) -> None:
        """Check that no imports of old pattern remain."""
        # Build import patterns to search for
        patterns = self._build_import_patterns()

        hits: list[str] = []
        for pattern in patterns:
            result = self._grep(pattern, "nomarr/")
            hits.extend(result)

        if hits:
            self.issues.append(f"Found {len(hits)} import(s) of old pattern")
            self.details["imports"] = hits[:10]  # Limit output

    def check_string_references(self) -> None:
        """Check for string references to old function/class names."""
        parts = self.old_pattern.split(".")
        if len(parts) < 2:
            return

        # Search for the leaf name (function/class name)
        leaf_name = parts[-1]

        # Skip very generic names
        if leaf_name in ("get", "set", "run", "start", "stop", "init"):
            return

        # Grep for usage patterns
        patterns = [
            rf"\.{leaf_name}\(",  # method calls
            rf"{leaf_name}\(",  # function calls
        ]

        hits: list[str] = []
        for pattern in patterns:
            result = self._grep(pattern, "nomarr/", is_regex=True)
            # Filter out the definition itself and test files
            result = [h for h in result if "def " + leaf_name not in h and "/tests/" not in h]
            hits.extend(result)

        if hits:
            self.warnings.append(
                f"Found {len(hits)} possible reference(s) to '{leaf_name}' (review manually)"
            )
            self.details["references"] = hits[:10]

    def check_skill_references(self) -> None:
        """Check that no skills reference the old pattern."""
        if not SKILLS_DIR.exists():
            return

        # Convert module path to file path pattern too
        file_pattern = self.old_pattern.replace(".", "/") + ".py"
        file_pattern = file_pattern.replace("nomarr/", "nomarr/")

        patterns = [self.old_pattern, file_pattern]
        hits: list[str] = []

        for skill_dir in SKILLS_DIR.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            content = skill_file.read_text(encoding="utf-8")
            for pattern in patterns:
                if pattern in content:
                    hits.append(f"{skill_dir.name}: references '{pattern}'")

        if hits:
            self.issues.append(f"Found {len(hits)} skill reference(s) to old pattern")
            self.details["skills"] = hits

    def check_ruff_ban(self) -> None:
        """Check if there's a ruff ban for the old pattern (only when expect_ban=True)."""
        if not self.expect_ban:
            return

        if not RUFF_TOML.exists():
            self.issues.append(
                f"Expected ruff ban for '{self.old_pattern}' but ruff.toml not found"
            )
            return

        content = RUFF_TOML.read_text(encoding="utf-8")

        # Check if pattern is banned
        if self.old_pattern in content:
            return  # Good - it's banned

        # Check for partial match (module without function)
        parts = self.old_pattern.split(".")
        for i in range(len(parts), 1, -1):
            partial = ".".join(parts[:i])
            if f'"{partial}"' in content:
                return  # Partial ban exists

        self.issues.append(f"Expected ruff ban for '{self.old_pattern}' not found in ruff.toml")

    def check_todo_comments(self) -> None:
        """Check for TODO/DEPRECATED comments about the old pattern."""
        parts = self.old_pattern.split(".")
        leaf_name = parts[-1]

        patterns = [
            rf"TODO.*{leaf_name}",
            rf"DEPRECATED.*{leaf_name}",
            rf"FIXME.*{leaf_name}",
            rf"# .*remove.*{leaf_name}",
        ]

        hits: list[str] = []
        for pattern in patterns:
            result = self._grep(pattern, "nomarr/", is_regex=True)
            hits.extend(result)

        if hits:
            self.issues.append(f"Found {len(hits)} TODO/DEPRECATED comment(s)")
            self.details["todos"] = hits[:10]

    def _build_import_patterns(self) -> list[str]:
        """Build grep patterns for import statements."""
        parts = self.old_pattern.split(".")
        patterns = []

        # Full module import: from nomarr.x.y import z
        if len(parts) >= 2:
            module_path = ".".join(parts[:-1])
            name = parts[-1]
            patterns.append(f"from {module_path} import")
            patterns.append(f"from {module_path} import.*{name}")

        # Direct import: import nomarr.x.y.z
        patterns.append(f"import {self.old_pattern}")

        return patterns

    def _grep(self, pattern: str, path: str, is_regex: bool = False) -> list[str]:
        """Run grep and return matching lines."""
        cmd = ["grep", "-r", "-n"]
        if is_regex:
            cmd.append("-E")
        cmd.extend([pattern, path])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            if result.returncode == 0:
                return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return []


def print_text_report(result: MigrationCheckResult) -> None:
    """Print human-readable report."""
    status = "✅ COMPLETE" if result["complete"] else "❌ INCOMPLETE"

    print("=" * 60)
    print(f"Migration Check: {status}")
    print("=" * 60)
    print(f"Old pattern: {result['old_pattern']}")
    if result["new_pattern"]:
        print(f"New pattern: {result['new_pattern']}")
    print()

    if result["issues"]:
        print("ISSUES (must fix):")
        for issue in result["issues"]:
            print(f"  ❌ {issue}")
        print()

    if result["warnings"]:
        print("WARNINGS (review):")
        for warning in result["warnings"]:
            print(f"  ⚠️  {warning}")
        print()

    if result["details"]:
        print("DETAILS:")
        for category, items in result["details"].items():
            print(f"  {category}:")
            for item in items[:5]:
                print(f"    - {item}")
            if len(items) > 5:
                print(f"    ... and {len(items) - 5} more")
        print()

    if result["complete"]:
        print("Migration is complete! No traces of old pattern found.")
    else:
        print("Migration is incomplete. Fix the issues above.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check if a code migration is complete")
    parser.add_argument(
        "pattern",
        nargs="?",
        help="Old pattern to check (e.g., nomarr.helpers.old_module)",
    )
    parser.add_argument("--old", help="Old pattern (alternative to positional argument)")
    parser.add_argument("--new", help="New pattern to verify exists")
    parser.add_argument(
        "--expect-ban",
        action="store_true",
        help="Verify a ruff ban exists for this pattern (use when migration plan includes banning)",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    old_pattern = args.pattern or args.old
    if not old_pattern:
        parser.error("Must specify old pattern (positional or --old)")

    checker = MigrationChecker(
        old_pattern=old_pattern,
        new_pattern=args.new,
        expect_ban=args.expect_ban,
    )
    result = checker.check_all()

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print_text_report(result)


if __name__ == "__main__":
    main()
