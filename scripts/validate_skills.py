#!/usr/bin/env python3
"""Validate Agent Skills for format compliance and reference validity.

Usage:
    python scripts/validate_skills.py              # Validate all skills
    python scripts/validate_skills.py layer-helpers # Validate one skill
    python scripts/validate_skills.py --format=json # JSON output
    python scripts/validate_skills.py --check-refs  # Also check code references

Checks performed:
    - YAML frontmatter starts with `---`
    - Required fields: `name`, `description`
    - `name` matches directory name, lowercase with hyphens
    - `name` ≤ 64 chars, no consecutive hyphens
    - `description` ≤ 1024 chars, non-empty
    - Line count ≤ 500 (warning if exceeded)
    - Code references exist (with --check-refs)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Skills directory relative to repo root
SKILLS_DIR = Path(".github/skills")

# Validation constraints
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_LINE_COUNT = 500

# Regex patterns
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CONSECUTIVE_HYPHENS = re.compile(r"--")

# Reference patterns to check (file paths in markdown)
# Matches: `path/to/file.py`, [text](path/to/file.ext), `nomarr/module/file.py`
CODE_REF_PATTERNS = [
    re.compile(r"`(nomarr/[^`]+\.py)`"),  # Python module references
    re.compile(r"`(scripts/[^`]+\.py)`"),  # Script references
    re.compile(r"\]\(((?:nomarr|scripts|frontend)/[^)]+)\)"),  # Markdown links
]


@dataclass
class ValidationResult:
    """Result of validating a single skill."""

    skill_name: str
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_invalid_ref(self, ref: str) -> None:
        self.invalid_refs.append(ref)
        self.valid = False


def parse_frontmatter(content: str) -> tuple[dict[str, str], int]:
    """Parse YAML frontmatter from markdown content.

    Returns:
        Tuple of (frontmatter dict, line count of frontmatter)

    """
    lines = content.split("\n")

    if not lines or lines[0].strip() != "---":
        return {}, 0

    # Find closing ---
    end_idx = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return {}, 0

    # Parse YAML (simple key: value parsing)
    frontmatter: dict[str, str] = {}
    current_key = None
    current_value_lines: list[str] = []

    for line in lines[1:end_idx]:
        # Check for new key
        if ":" in line and not line.startswith(" ") and not line.startswith("\t"):
            # Save previous key if exists
            if current_key:
                frontmatter[current_key] = " ".join(current_value_lines).strip()

            key, _, value = line.partition(":")
            current_key = key.strip()
            current_value_lines = [value.strip()]
        elif current_key:
            # Continuation of previous value
            current_value_lines.append(line.strip())

    # Save last key
    if current_key:
        frontmatter[current_key] = " ".join(current_value_lines).strip()

    return frontmatter, end_idx + 1


def validate_name(name: str, dir_name: str, result: ValidationResult) -> None:
    """Validate skill name field."""
    if not name:
        result.add_error("Missing required field: name")
        return

    if len(name) > MAX_NAME_LENGTH:
        result.add_error(f"name exceeds {MAX_NAME_LENGTH} chars: {len(name)}")

    if not NAME_PATTERN.match(name):
        result.add_error(f"name must be lowercase alphanumeric with hyphens: '{name}'")

    if CONSECUTIVE_HYPHENS.search(name):
        result.add_error(f"name contains consecutive hyphens: '{name}'")

    if name != dir_name:
        result.add_error(f"name '{name}' does not match directory '{dir_name}'")


def validate_description(description: str, result: ValidationResult) -> None:
    """Validate skill description field."""
    if not description:
        result.add_error("Missing required field: description")
        return

    if len(description) > MAX_DESCRIPTION_LENGTH:
        result.add_error(f"description exceeds {MAX_DESCRIPTION_LENGTH} chars: {len(description)}")

    # Check for WHAT and WHEN indicators
    desc_lower = description.lower()
    has_when = any(word in desc_lower for word in ["when", "use when", "trigger"])
    if not has_when:
        result.add_warning("description should explain WHEN to use this skill")


def find_code_references(content: str) -> list[str]:
    """Extract code file references from markdown content."""
    refs: list[str] = []
    for pattern in CODE_REF_PATTERNS:
        refs.extend(pattern.findall(content))
    return refs


def check_references(content: str, repo_root: Path, result: ValidationResult) -> None:
    """Check that code references point to existing files."""
    refs = find_code_references(content)

    for ref in refs:
        # Clean up the reference
        ref_path = ref.strip("`").strip()

        # Skip URLs and anchors
        if ref_path.startswith("http") or "#" in ref_path:
            continue

        # Check if file exists
        full_path = repo_root / ref_path
        if not full_path.exists():
            result.add_invalid_ref(ref_path)


def validate_skill(skill_dir: Path, repo_root: Path, check_refs: bool = False) -> ValidationResult:
    """Validate a single skill directory."""
    result = ValidationResult(skill_name=skill_dir.name)

    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        result.add_error(f"Missing SKILL.md in {skill_dir}")
        return result

    content = skill_file.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Check frontmatter
    if not content.startswith("---"):
        result.add_error("SKILL.md must start with YAML frontmatter (---)")
        return result

    frontmatter, _ = parse_frontmatter(content)

    if not frontmatter:
        result.add_error("Could not parse YAML frontmatter")
        return result

    # Validate name
    name = frontmatter.get("name", "")
    validate_name(name, skill_dir.name, result)

    # Validate description
    description = frontmatter.get("description", "")
    validate_description(description, result)

    # Check line count
    line_count = len(lines)
    if line_count > MAX_LINE_COUNT:
        result.add_warning(
            f"SKILL.md exceeds {MAX_LINE_COUNT} lines ({line_count}). Consider moving content to references/"
        )

    # Check code references if requested
    if check_refs:
        check_references(content, repo_root, result)

    return result


def find_all_skills(repo_root: Path) -> list[Path]:
    """Find all skill directories."""
    skills_path = repo_root / SKILLS_DIR
    if not skills_path.exists():
        return []

    return [d for d in skills_path.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]


def format_text_output(results: list[ValidationResult]) -> str:
    """Format results as human-readable text."""
    output_lines: list[str] = []

    passed = sum(1 for r in results if r.valid)
    total = len(results)

    output_lines.append(f"\nSkill Validation: {passed}/{total} passed\n")
    output_lines.append("=" * 50)

    for result in results:
        status = "✅ PASS" if result.valid else "❌ FAIL"
        output_lines.append(f"\n{result.skill_name}: {status}")

        for error in result.errors:
            output_lines.append(f"  ERROR: {error}")

        for warning in result.warnings:
            output_lines.append(f"  WARNING: {warning}")

        for ref in result.invalid_refs:
            output_lines.append(f"  INVALID REF: {ref}")

    output_lines.append("\n" + "=" * 50)

    if passed == total:
        output_lines.append("All skills valid!")
    else:
        output_lines.append(f"{total - passed} skill(s) have errors.")

    return "\n".join(output_lines)


def format_json_output(results: list[ValidationResult]) -> str:
    """Format results as JSON."""
    data = {
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.valid),
            "failed": sum(1 for r in results if not r.valid),
        },
        "results": [
            {
                "skill": r.skill_name,
                "valid": r.valid,
                "errors": r.errors,
                "warnings": r.warnings,
                "invalid_refs": r.invalid_refs,
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Agent Skills")
    parser.add_argument("skill", nargs="?", help="Specific skill to validate (default: all)")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    parser.add_argument("--check-refs", action="store_true", help="Check that code references exist")
    args = parser.parse_args()

    # Find repo root (script is in scripts/)
    repo_root = Path(__file__).parent.parent

    # Find skills to validate
    if args.skill:
        skill_dir = repo_root / SKILLS_DIR / args.skill
        if not skill_dir.exists():
            print(f"Error: Skill '{args.skill}' not found at {skill_dir}", file=sys.stderr)
            return 1
        skills = [skill_dir]
    else:
        skills = find_all_skills(repo_root)
        if not skills:
            print(f"No skills found in {repo_root / SKILLS_DIR}", file=sys.stderr)
            return 1

    # Validate each skill
    results = [validate_skill(skill, repo_root, check_refs=args.check_refs) for skill in sorted(skills)]

    # Output results
    if args.format == "json":
        print(format_json_output(results))
    else:
        print(format_text_output(results))

    # Exit code: 0 if all valid, 1 if any errors
    return 0 if all(r.valid for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
