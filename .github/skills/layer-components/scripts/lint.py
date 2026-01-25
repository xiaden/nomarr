#!/usr/bin/env python3
"""Run all linters on components layer.

Only shows errors and high-complexity warnings (D, E, F grades).
lint-imports shows full output for contract violation detection.
"""

import subprocess
import sys

LAYER = "nomarr/components"


def run_quiet(cmd: list[str], name: str) -> int:
    """Run command and only show output if there are issues."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or result.stdout.strip() or result.stderr.strip():
        print(f"\n=== {name} ===")
        if result.stdout.strip():
            print(result.stdout)
        if result.stderr.strip():
            print(result.stderr, file=sys.stderr)
    return result.returncode


def run_radon_filtered(layer: str) -> int:
    """Run radon and only show D, E, F complexity grades."""
    result = subprocess.run(
        ["radon", "cc", layer, "-a", "-s", "--no-assert"],
        capture_output=True,
        text=True,
    )

    # Filter to only D, E, F grades (high complexity)
    bad_lines = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped and any(f" - {grade} " in line or line.endswith(f" - {grade}") for grade in ["D", "E", "F"]):
            bad_lines.append(line)
        if "Average complexity:" in line:
            if any(f": {grade} " in line for grade in ["D", "E", "F"]):
                bad_lines.append(line)

    if bad_lines:
        print("\n=== radon (complexity D/E/F only) ===")
        for line in bad_lines:
            print(line)
        return 1
    return 0


def main() -> int:
    """Run all linters, return non-zero if any fail."""
    exit_code = 0

    exit_code |= run_quiet(["ruff", "check", LAYER], "ruff")
    exit_code |= run_quiet(["mypy", LAYER], "mypy")
    exit_code |= run_quiet(["vulture", LAYER, "--min-confidence", "100"], "vulture")
    exit_code |= run_quiet(["bandit", "-r", LAYER, "-q"], "bandit")
    exit_code |= run_radon_filtered(LAYER)

    # lint-imports: show full output for contract violations
    print("\n=== lint-imports ===")
    result = subprocess.run(["lint-imports"])
    exit_code |= result.returncode

    if exit_code == 0:
        print(f"\n✅ All linters passed for {LAYER}")
    else:
        print(f"\n❌ Linter issues found in {LAYER}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
