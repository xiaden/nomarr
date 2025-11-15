#!/usr/bin/env python3
"""
Automated Slop & Drift Detection

Uses existing tools to discover code quality issues:
- radon: Complexity metrics
- import-linter: Architecture violations
- flake8 + plugins: Code smells, overcomplicated patterns, commented code
- Custom analysis: AI slop patterns

Output is designed to TEACH you what patterns exist in your codebase.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
NOMARR_DIR = ROOT / "nomarr"
REPORTS_DIR = ROOT / "qc_reports"


def run_command(cmd: list[str], description: str) -> dict[str, Any]:
    """Run a command and capture output."""
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 60}\n")

    try:
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)

        return {
            "description": description,
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "description": description,
            "command": " ".join(cmd),
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after 120 seconds",
            "success": False,
        }
    except Exception as e:
        return {
            "description": description,
            "command": " ".join(cmd),
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False,
        }


def main():
    """Run all slop/drift detection tools."""
    REPORTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"slop_detection_{timestamp}.txt"
    json_file = REPORTS_DIR / f"slop_detection_{timestamp}.json"

    results = []

    print("🔍 Slop & Drift Detection")
    print(f"Timestamp: {timestamp}")
    print(f"Target: {NOMARR_DIR}")

    # 1. Radon - Cyclomatic Complexity
    results.append(
        run_command(
            [sys.executable, "-m", "radon", "cc", str(NOMARR_DIR), "-a", "-s"],
            "Radon: Cyclomatic Complexity (shows complex functions)",
        )
    )

    # 2. Radon - Maintainability Index
    results.append(
        run_command(
            [sys.executable, "-m", "radon", "mi", str(NOMARR_DIR), "-s"],
            "Radon: Maintainability Index (A=excellent, C=needs work, F=unmaintainable)",
        )
    )

    # 3. Radon - Raw Metrics (lines of code, comments, etc)
    results.append(
        run_command(
            [sys.executable, "-m", "radon", "raw", str(NOMARR_DIR), "-s"],
            "Radon: Raw Metrics (LOC, comments, blank lines)",
        )
    )

    # 4. Import Linter - Architecture Violations
    results.append(
        run_command(
            ["lint-imports"],
            "Import Linter: Architecture violations (layered dependency rules)",
        )
    )

    # 5. Flake8 with all plugins - Code Smells
    results.append(
        run_command(
            [
                sys.executable,
                "-m",
                "flake8",
                str(NOMARR_DIR),
                "--max-complexity",
                "15",
                "--max-cognitive-complexity",
                "15",
                "--extend-ignore",
                "E501,W503,E203",
            ],  # Ignore line length (ruff handles), line break before binary op, whitespace before ':'
            "Flake8: Code smells (complexity, simplify, eradicate, variable names)",
        )
    )

    # 6. Flake8 with stricter complexity thresholds
    results.append(
        run_command(
            [
                sys.executable,
                "-m",
                "flake8",
                str(NOMARR_DIR),
                "--max-complexity",
                "10",
                "--max-cognitive-complexity",
                "10",
                "--select",
                "C901,CCR001",  # Only complexity warnings
                "--extend-ignore",
                "E501,W503,E203",
            ],
            "Flake8: Strict complexity check (threshold=10)",
        )
    )

    # 7. Eradicate standalone - Commented-out code
    results.append(
        run_command(
            [sys.executable, "-m", "eradicate", str(NOMARR_DIR), "--recursive"], "Eradicate: Finds commented-out code"
        )
    )

    # Write report
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("Slop & Drift Detection Report\n")
        f.write(f"Generated: {timestamp}\n")
        f.write(f"{'=' * 80}\n\n")

        for result in results:
            f.write(f"\n{'=' * 80}\n")
            f.write(f"{result['description']}\n")
            f.write(f"Command: {result['command']}\n")
            f.write(f"Status: {'✅ SUCCESS' if result['success'] else '❌ FAILED'}\n")
            f.write(f"{'=' * 80}\n\n")

            if result["stdout"]:
                f.write("STDOUT:\n")
                f.write(result["stdout"])
                f.write("\n\n")

            if result["stderr"]:
                f.write("STDERR:\n")
                f.write(result["stderr"])
                f.write("\n\n")

    # Write JSON for programmatic access
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": timestamp, "results": results}, f, indent=2)

    print(f"\n{'=' * 80}")
    print(f"✅ Report saved to: {report_file}")
    print(f"✅ JSON data saved to: {json_file}")
    print(f"{'=' * 80}\n")

    # Print summary
    print("📊 Summary:")
    for result in results:
        status = "✅" if result["success"] else "❌"
        print(f"  {status} {result['description']}")

    # Check for critical issues
    failed_count = sum(1 for r in results if not r["success"])
    if failed_count > 0:
        print(f"\n⚠️  {failed_count} check(s) failed or found issues")
        return 1

    print("\n✨ All checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
